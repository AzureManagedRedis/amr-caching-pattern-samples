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

@description('Resource ID of the function app identity.')
param funcIdentityId string
@description('Principal (object) ID of the function app identity.')
param funcIdentityPrincipalId string
@description('Client ID of the function app identity.')
param funcIdentityClientId string

var prefix = 'retail'
var placeholderImage = 'mcr.microsoft.com/azuredocs/containerapps-helloworld:latest'
var cosmosDatabaseName = 'retail'

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
// Azure Cosmos DB for NoSQL (serverless, Microsoft Entra-only auth)
// -------------------------------------------------------------------------
resource cosmos 'Microsoft.DocumentDB/databaseAccounts@2024-11-15' = {
  name: '${prefix}-cosmos-${resourceToken}'
  location: location
  tags: tags
  kind: 'GlobalDocumentDB'
  properties: {
    databaseAccountOfferType: 'Standard'
    locations: [
      { locationName: location, failoverPriority: 0, isZoneRedundant: false }
    ]
    capabilities: [ { name: 'EnableServerless' } ]
    consistencyPolicy: { defaultConsistencyLevel: 'Session' }
    // Keys are off: the app, the function, and the developer use Microsoft Entra ID.
    disableLocalAuth: true
    publicNetworkAccess: 'Enabled'
    // 0.0.0.0 accepts connections only from Azure datacenters, which covers the
    // container app and the function app. To run the app locally, add your IP
    // (see "Run locally" in the README).
    ipRules: [ { ipAddressOrRange: '0.0.0.0' } ]
    minimalTlsVersion: 'Tls12'
  }
}

resource cosmosDb 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases@2024-11-15' = {
  parent: cosmos
  name: cosmosDatabaseName
  properties: {
    resource: { id: cosmosDatabaseName }
  }
}

// The article's containers. Data-plane roles can't create databases or containers,
// so the template creates them, including `leases` for the change feed triggers.
var containers = [
  // TTL on with no default (-1), so soft-deleted products can expire.
  { name: 'products', partitionKey: '/categoryId', defaultTtl: -1 }
  { name: 'orders', partitionKey: '/customerId', defaultTtl: 0 }
  { name: 'reference', partitionKey: '/type', defaultTtl: 0 }
  { name: 'leases', partitionKey: '/id', defaultTtl: 0 }
]

@batchSize(1)
resource cosmosContainers 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers@2024-11-15' = [for c in containers: {
  parent: cosmosDb
  name: c.name
  properties: {
    resource: union(
      {
        id: c.name
        partitionKey: { paths: [ c.partitionKey ], kind: 'Hash' }
      },
      c.defaultTtl != 0 ? { defaultTtl: c.defaultTtl } : {}
    )
  }
}]

// Cosmos DB Built-in Data Contributor: read and write items, nothing else.
var cosmosDataContributor = '${cosmos.id}/sqlRoleDefinitions/00000000-0000-0000-0000-000000000002'

resource cosmosAppAccess 'Microsoft.DocumentDB/databaseAccounts/sqlRoleAssignments@2024-11-15' = {
  parent: cosmos
  name: guid(cosmos.id, identityPrincipalId, 'data-contributor')
  properties: {
    roleDefinitionId: cosmosDataContributor
    principalId: identityPrincipalId
    scope: cosmos.id
  }
}

resource cosmosFuncAccess 'Microsoft.DocumentDB/databaseAccounts/sqlRoleAssignments@2024-11-15' = {
  parent: cosmos
  name: guid(cosmos.id, funcIdentityPrincipalId, 'data-contributor')
  properties: {
    roleDefinitionId: cosmosDataContributor
    principalId: funcIdentityPrincipalId
    scope: cosmos.id
  }
  dependsOn: [ cosmosAppAccess ]  // role assignments on one account are applied one at a time
}

resource cosmosDevAccess 'Microsoft.DocumentDB/databaseAccounts/sqlRoleAssignments@2024-11-15' = if (!empty(developerId)) {
  parent: cosmos
  name: guid(cosmos.id, developerId, 'data-contributor')
  properties: {
    roleDefinitionId: cosmosDataContributor
    principalId: developerId
    scope: cosmos.id
  }
  dependsOn: [ cosmosFuncAccess ]
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
    // Listings, products, and carts carry a TTL; reference data and the best-sellers
    // ranking don't. volatile-lru evicts only keys that have a TTL, which protects the others.
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
            { name: 'COSMOS_ENDPOINT', value: cosmos.properties.documentEndpoint }
            { name: 'COSMOS_DATABASE', value: cosmosDatabaseName }
            { name: 'REDIS_HOST', value: redis.properties.hostName }
            { name: 'REDIS_PORT', value: '10000' }
            { name: 'AUTO_SEED', value: 'true' }
          ]
        }
      ]
      scale: { minReplicas: 1, maxReplicas: 3 }
    }
  }
  dependsOn: [ acrPull, cosmosContainers, cosmosAppAccess, redisAppAccess ]
}

// -------------------------------------------------------------------------
// Azure Functions (change feed triggers for event-driven refresh and ranking)
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

// The change feed triggers need a host that keeps running and polling. A Basic (B1)
// dedicated plan with Always On is a low-cost option that supports it.
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
      linuxFxVersion: 'Python|3.12'
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
        // Identity-based connection for the Azure Cosmos DB trigger. With a
        // user-assigned identity, the trigger also needs the credential type and client ID.
        { name: 'CosmosDBConnection__accountEndpoint', value: cosmos.properties.documentEndpoint }
        { name: 'CosmosDBConnection__credential', value: 'managedidentity' }
        { name: 'CosmosDBConnection__clientId', value: funcIdentityClientId }
        // Used by shared/cache.py (DefaultAzureCredential picks the identity from AZURE_CLIENT_ID).
        { name: 'AZURE_CLIENT_ID', value: funcIdentityClientId }
        { name: 'REDIS_HOST', value: redis.properties.hostName }
      ]
    }
  }
  dependsOn: [ storageAccess, cosmosContainers, cosmosFuncAccess, redisFuncAccess ]
}

// Turn off basic (username and password) publishing credentials. azd deploys
// with your Microsoft Entra sign-in instead.
resource funcScmCredentials 'Microsoft.Web/sites/basicPublishingCredentialsPolicies@2024-04-01' = {
  parent: func
  name: 'scm'
  properties: { allow: false }
}

resource funcFtpCredentials 'Microsoft.Web/sites/basicPublishingCredentialsPolicies@2024-04-01' = {
  parent: func
  name: 'ftp'
  properties: { allow: false }
}

output registryLoginServer string = registry.properties.loginServer
output cosmosAccountName string = cosmos.name
output cosmosEndpoint string = cosmos.properties.documentEndpoint
output cosmosDatabaseName string = cosmosDatabaseName
output redisHost string = redis.properties.hostName
output funcAppName string = func.name
output webUri string = 'https://${web.properties.configuration.ingress.fqdn}'
