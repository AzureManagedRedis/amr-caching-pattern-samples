@description('Location for all resources.')
param location string
param tags object
param resourceToken string
@description('Whether the web container app already exists. When true, provisioning keeps the running image; azd sets the built image during the deploy step.')
param webExists bool = false
@description('Object ID of the developer who deployed the sample, granted data access for running locally. Empty to skip.')
param developerId string = ''

@description('Resource ID of the web app identity.')
param identityId string
@description('Principal (object) ID of the web app identity.')
param identityPrincipalId string
@description('Client ID of the web app identity.')
param identityClientId string
@description('Name of the web app identity (the SQL server Microsoft Entra admin).')
param identityName string

@description('Resource ID of the function app identity.')
param funcIdentityId string
@description('Principal (object) ID of the function app identity.')
param funcIdentityPrincipalId string
@description('Client ID of the function app identity.')
param funcIdentityClientId string
@description('Name of the function app identity (the database user the SQL trigger runs as).')
param funcIdentityName string

var prefix = 'retail'
var placeholderImage = 'mcr.microsoft.com/azuredocs/containerapps-helloworld:latest'
var sqlDatabaseName = 'retail'

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
// Azure SQL Database (Microsoft Entra-only auth)
// -------------------------------------------------------------------------
resource sqlServer 'Microsoft.Sql/servers@2023-08-01' = {
  name: '${prefix}-sql-${resourceToken}'
  location: location
  tags: tags
  properties: {
    minimalTlsVersion: '1.2'
    publicNetworkAccess: 'Enabled'
    // The web app's identity is the Microsoft Entra admin, so it can create the
    // schema, enable change tracking, and grant the function identity on first start.
    administrators: {
      administratorType: 'ActiveDirectory'
      principalType: 'Application'
      login: identityName
      sid: identityPrincipalId
      tenantId: subscription().tenantId
      azureADOnlyAuthentication: true
    }
  }
}

resource sqlDatabase 'Microsoft.Sql/servers/databases@2023-08-01' = {
  parent: sqlServer
  name: sqlDatabaseName
  location: location
  tags: tags
  sku: { name: 'Basic', tier: 'Basic' }
  properties: {
    requestedBackupStorageRedundancy: 'Local'
  }
}

resource sqlFirewall 'Microsoft.Sql/servers/firewallRules@2023-08-01' = {
  parent: sqlServer
  name: 'AllowAzureServices'
  properties: { startIpAddress: '0.0.0.0', endIpAddress: '0.0.0.0' }
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
    // Required as of API 2025-07-01. The app connects over the public endpoint,
    // so public network access is enabled.
    publicNetworkAccess: 'Enabled'
  }
}

resource redisDb 'Microsoft.Cache/redisEnterprise/databases@2025-07-01' = {
  parent: redis
  name: 'default'
  properties: {
    clientProtocol: 'Encrypted'
    port: 10000
    // OSS clustering policy exposes the Redis Cluster API; the app and the function
    // connect with redis.cluster.RedisCluster, which routes each key to its shard.
    clusteringPolicy: 'OSSCluster'
    // Product pages carry a TTL; reference data and pending view counts don't.
    // volatile-lru evicts only keys that have a TTL, which protects the others.
    evictionPolicy: 'VolatileLRU'
    accessKeysAuthentication: 'Disabled'
  }
}

resource redisAppAccess 'Microsoft.Cache/redisEnterprise/databases/accessPolicyAssignments@2025-07-01' = {
  parent: redisDb
  name: 'appidentity'  // alphanumeric only, 1-60 chars (no hyphens)
  properties: {
    accessPolicyName: 'default'
    user: { objectId: identityPrincipalId }
  }
}

resource redisFuncAccess 'Microsoft.Cache/redisEnterprise/databases/accessPolicyAssignments@2025-07-01' = {
  parent: redisDb
  name: 'funcidentity'
  properties: {
    accessPolicyName: 'default'
    user: { objectId: funcIdentityPrincipalId }
  }
  dependsOn: [ redisAppAccess ]  // access policy assignments on one database are applied one at a time
}

resource redisDevAccess 'Microsoft.Cache/redisEnterprise/databases/accessPolicyAssignments@2025-07-01' = if (!empty(developerId)) {
  parent: redisDb
  name: 'developer'
  properties: {
    accessPolicyName: 'default'
    user: { objectId: developerId }
  }
  dependsOn: [ redisFuncAccess ]
}

// -------------------------------------------------------------------------
// Container Apps (storefront)
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
module webImage 'fetch-image.bicep' = {
  name: 'web-image'
  params: {
    name: '${prefix}-web-${resourceToken}'
    exists: webExists
  }
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
          image: webExists ? webImage.outputs.image : placeholderImage
          resources: { cpu: json('0.5'), memory: '1.0Gi' }
          env: [
            { name: 'AZURE_CLIENT_ID', value: identityClientId }
            { name: 'SQL_SERVER', value: sqlServer.properties.fullyQualifiedDomainName }
            { name: 'SQL_DATABASE', value: sqlDatabaseName }
            { name: 'REDIS_HOST', value: redis.properties.hostName }
            { name: 'REDIS_PORT', value: '10000' }
            { name: 'REDIS_USER_OBJECT_ID', value: identityPrincipalId }
            { name: 'FUNC_IDENTITY_NAME', value: funcIdentityName }
            { name: 'FUNC_IDENTITY_CLIENT_ID', value: funcIdentityClientId }
            { name: 'DEVELOPER_OBJECT_ID', value: developerId }
            { name: 'RUN_JOBS', value: 'true' }
            { name: 'AUTO_SEED', value: 'true' }
          ]
        }
      ]
      scale: { minReplicas: 1, maxReplicas: 3 }
    }
  }
  dependsOn: [ acrPull, sqlDatabase, sqlFirewall, redisAppAccess ]
}

// -------------------------------------------------------------------------
// Azure Functions (SQL trigger for event-driven invalidation)
// -------------------------------------------------------------------------
// Identity-based host storage: no shared keys.
resource storage 'Microsoft.Storage/storageAccounts@2025-01-01' = {
  name: '${prefix}st${resourceToken}'
  location: location
  tags: tags
  kind: 'StorageV2'
  sku: { name: 'Standard_LRS' }
  properties: {
    allowSharedKeyAccess: false
    allowBlobPublicAccess: false
    minimumTlsVersion: 'TLS1_2'
  }
}

var storageRoles = [
  'b7e6dc6d-f1e8-4753-8033-0f276bb0955b' // Storage Blob Data Owner
  '974c5e8b-45b9-4653-ba55-5f855dd0fb88' // Storage Queue Data Contributor
  '0a9a7e1f-b9d0-4cc4-a60d-0319b160aaa3' // Storage Table Data Contributor
]

resource storageAccess 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for role in storageRoles: {
  name: guid(storage.id, funcIdentityId, role)
  scope: storage
  properties: {
    principalId: funcIdentityPrincipalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', role)
  }
}]

// The SQL trigger needs a plan that keeps the host running. A Basic (B1) dedicated
// plan with Always On is the lowest-cost option that supports it.
resource plan 'Microsoft.Web/serverfarms@2024-04-01' = {
  name: '${prefix}-plan-${resourceToken}'
  location: location
  tags: tags
  kind: 'linux'
  sku: { name: 'B1', tier: 'Basic' }
  properties: { reserved: true }
}

resource func 'Microsoft.Web/sites@2024-04-01' = {
  name: '${prefix}-func-${resourceToken}'
  location: location
  tags: union(tags, { 'azd-service-name': 'func' })
  kind: 'functionapp,linux'
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: { '${funcIdentityId}': {} }
  }
  properties: {
    serverFarmId: plan.id
    httpsOnly: true
    siteConfig: {
      linuxFxVersion: 'Python|3.11'
      alwaysOn: true
      minTlsVersion: '1.2'
      ftpsState: 'Disabled'
      appSettings: [
        { name: 'FUNCTIONS_EXTENSION_VERSION', value: '~4' }
        { name: 'FUNCTIONS_WORKER_RUNTIME', value: 'python' }
        { name: 'AzureWebJobsStorage__accountName', value: storage.name }
        { name: 'AzureWebJobsStorage__credential', value: 'managedidentity' }
        { name: 'AzureWebJobsStorage__clientId', value: funcIdentityClientId }
        { name: 'SCM_DO_BUILD_DURING_DEPLOYMENT', value: 'true' }
        { name: 'ENABLE_ORYX_BUILD', value: 'true' }
        // The SQL trigger connects as the function identity (User Id = its client ID).
        { name: 'SqlConnectionString', value: 'Server=tcp:${sqlServer.properties.fullyQualifiedDomainName},1433;Database=${sqlDatabaseName};Encrypt=True;Authentication=Active Directory Managed Identity;User Id=${funcIdentityClientId};' }
        { name: 'AZURE_CLIENT_ID', value: funcIdentityClientId }
        { name: 'REDIS_HOST', value: redis.properties.hostName }
        { name: 'REDIS_USER_OBJECT_ID', value: funcIdentityPrincipalId }
      ]
    }
  }
  dependsOn: [ storageAccess, sqlFirewall, redisFuncAccess ]
}

output registryLoginServer string = registry.properties.loginServer
output sqlServerHost string = sqlServer.properties.fullyQualifiedDomainName
output sqlDatabaseName string = sqlDatabaseName
output redisHost string = redis.properties.hostName
output funcAppName string = func.name
output webUri string = 'https://${web.properties.configuration.ingress.fqdn}'
