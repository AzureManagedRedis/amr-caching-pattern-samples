@description('Location for all resources.')
param location string
param tags object
param resourceToken string
@description('Whether the web container app already exists. When true, provisioning keeps the running image; azd sets the built image during the deploy step.')
param webExists bool = false

@description('Resource ID of the user-assigned identity.')
param identityId string
@description('Principal (object) ID of the user-assigned identity.')
param identityPrincipalId string
@description('Client ID of the user-assigned identity.')
param identityClientId string
@description('Name of the user-assigned identity (used as the Postgres role).')
param identityName string

var prefix = 'retail'
var placeholderImage = 'mcr.microsoft.com/azuredocs/containerapps-helloworld:latest'

// -------------------------------------------------------------------------
// Container registry (image build target for azd)
// -------------------------------------------------------------------------
resource registry 'Microsoft.ContainerRegistry/registries@2025-11-01' = {
  name: '${prefix}acr${resourceToken}'
  location: location
  tags: tags
  sku: { name: 'Basic' }
  properties: { adminUserEnabled: false }
}

resource acrPull 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(registry.id, identityId, 'acrpull')
  scope: registry
  properties: {
    principalId: identityPrincipalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '7f951dda-4ed3-4680-a7ca-43fe172d538d')
  }
}

// -------------------------------------------------------------------------
// Azure Database for PostgreSQL flexible server (Entra-only auth)
// -------------------------------------------------------------------------
resource postgres 'Microsoft.DBforPostgreSQL/flexibleServers@2025-08-01' = {
  name: '${prefix}-pg-${resourceToken}'
  location: location
  tags: tags
  sku: { name: 'Standard_B1ms', tier: 'Burstable' }
  properties: {
    version: '16'
    storage: { storageSizeGB: 32 }
    authConfig: {
      activeDirectoryAuth: 'Enabled'
      passwordAuth: 'Disabled'
    }
    highAvailability: { mode: 'Disabled' }
  }
}

resource database 'Microsoft.DBforPostgreSQL/flexibleServers/databases@2025-08-01' = {
  parent: postgres
  name: 'retail'
}

resource pgFirewall 'Microsoft.DBforPostgreSQL/flexibleServers/firewallRules@2025-08-01' = {
  parent: postgres
  name: 'AllowAzureServices'
  properties: { startIpAddress: '0.0.0.0', endIpAddress: '0.0.0.0' }
}

// The container app's identity is an Entra admin, so it can connect and own the schema.
resource pgAdmin 'Microsoft.DBforPostgreSQL/flexibleServers/administrators@2025-08-01' = {
  parent: postgres
  name: identityPrincipalId
  properties: {
    principalType: 'ServicePrincipal'
    principalName: identityName
    tenantId: subscription().tenantId
  }
  dependsOn: [ pgFirewall ]
}

// -------------------------------------------------------------------------
// Azure Managed Redis (Entra-only auth)
// -------------------------------------------------------------------------
resource redis 'Microsoft.Cache/redisEnterprise@2025-07-01' = {
  name: '${prefix}-amr-${resourceToken}'
  location: location
  tags: tags
  sku: { name: 'Balanced_B0' }
  properties: {
    // Required as of API 2025-07-01. The app connects over the public endpoint
    // (with firewall rules), so public network access is enabled.
    publicNetworkAccess: 'Enabled'
  }
}

resource redisDb 'Microsoft.Cache/redisEnterprise/databases@2025-07-01' = {
  parent: redis
  name: 'default'
  properties: {
    clientProtocol: 'Encrypted'
    port: 10000
    // OSS clustering policy exposes the Redis Cluster API. The app connects with a
    // cluster-aware client (redis.asyncio.RedisCluster) that routes each key to its
    // shard - the configuration this sample highlights for latency and throughput.
    clusteringPolicy: 'OSSCluster'
    // Cache keys carry TTLs (product cache-aside, order status), so evict expiring
    // keys first under memory pressure; TTL-less reference data is retained.
    evictionPolicy: 'VolatileLRU'
    accessKeysAuthentication: 'Disabled'
  }
}

resource redisAccess 'Microsoft.Cache/redisEnterprise/databases/accessPolicyAssignments@2025-07-01' = {
  parent: redisDb
  name: 'appidentity'  // alphanumeric only, 1-60 chars (no hyphens)
  properties: {
    accessPolicyName: 'default'
    user: { objectId: identityPrincipalId }
  }
}

// -------------------------------------------------------------------------
// Container Apps
// -------------------------------------------------------------------------
resource env 'Microsoft.App/managedEnvironments@2026-01-01' = {
  name: '${prefix}-env-${resourceToken}'
  location: location
  tags: tags
  properties: {}
}

// azd builds and pushes the image during its deploy step, which runs after
// provisioning. To avoid referencing an image tag that doesn't exist yet,
// provisioning uses a placeholder on first create and preserves the running image
// on updates; the deploy step then sets the freshly built image.
resource existingWeb 'Microsoft.App/containerApps@2026-01-01' existing = if (webExists) {
  name: '${prefix}-web-${resourceToken}'
}

resource web 'Microsoft.App/containerApps@2026-01-01' = {
  name: '${prefix}-web-${resourceToken}'
  location: location
  tags: union(tags, { 'azd-service-name': 'web' })
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: { '${identityId}': {} }
  }
  properties: {
    managedEnvironmentId: env.id
    configuration: {
      activeRevisionsMode: 'Single'
      ingress: { external: true, targetPort: 8000, transport: 'auto' }
      registries: [
        { server: registry.properties.loginServer, identity: identityId }
      ]
    }
    template: {
      containers: [
        {
          name: 'web'
          #disable-next-line BCP318
          image: webExists ? existingWeb.properties.template.containers[0].image : placeholderImage
          resources: { cpu: json('0.5'), memory: '1.0Gi' }
          env: [
            { name: 'AZURE_CLIENT_ID', value: identityClientId }
            { name: 'POSTGRES_HOST', value: postgres.properties.fullyQualifiedDomainName }
            { name: 'POSTGRES_DB', value: 'retail' }
            { name: 'POSTGRES_USER', value: identityName }
            { name: 'POSTGRES_PORT', value: '5432' }
            { name: 'REDIS_HOST', value: redis.properties.hostName }
            { name: 'REDIS_PORT', value: '10000' }
            { name: 'REDIS_USERNAME', value: identityPrincipalId }
            { name: 'CACHE_TTL_SECONDS', value: '300' }
            { name: 'RUN_WORKER', value: 'true' }
            { name: 'AUTO_SEED', value: 'true' }
          ]
        }
      ]
      scale: { minReplicas: 1, maxReplicas: 3 }
    }
  }
  dependsOn: [ acrPull ]
}

output registryLoginServer string = registry.properties.loginServer
output postgresHost string = postgres.properties.fullyQualifiedDomainName
output redisHost string = redis.properties.hostName
output webUri string = 'https://${web.properties.configuration.ingress.fqdn}'
