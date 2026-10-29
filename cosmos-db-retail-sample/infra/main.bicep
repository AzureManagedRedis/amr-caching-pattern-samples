targetScope = 'subscription'

@minLength(1)
@maxLength(64)
@description('Name of the azd environment; used to derive resource names.')
param environmentName string

@minLength(1)
@description('Primary location for all resources.')
param location string

@description('Whether the web container app already exists. azd sets this so provisioning preserves the running image and the deploy step updates it.')
param webExists bool = false

@description('Object ID of the user running azd (set by azd). When it is a user, they get data access for running the app locally.')
param principalId string = ''
@description('Type of the principal running azd: User or ServicePrincipal (set by azd).')
param principalType string = 'User'
var tags = { 'azd-env-name': environmentName }
var resourceToken = toLower(uniqueString(subscription().id, environmentName, location))

resource rg 'Microsoft.Resources/resourceGroups@2025-04-01' = {
  name: 'rg-${environmentName}'
  location: location
  tags: tags
}

// The identities are provisioned first so their principal IDs are available as
// parameters to the resources module (a resource's runtime principalId cannot be
// used directly as another resource's name).
module identity 'identity.bicep' = {
  name: 'identity'
  scope: rg
  params: {
    location: location
    tags: tags
    resourceToken: resourceToken
  }
}

module resources 'resources.bicep' = {
  name: 'resources'
  scope: rg
  params: {
    location: location
    tags: tags
    resourceToken: resourceToken
    webExists: webExists
    developerId: principalType == 'User' ? principalId : ''
    identityId: identity.outputs.id
    identityPrincipalId: identity.outputs.principalId
    identityClientId: identity.outputs.clientId
    funcIdentityId: identity.outputs.funcId
    funcIdentityPrincipalId: identity.outputs.funcPrincipalId
    funcIdentityClientId: identity.outputs.funcClientId
  }
}

output AZURE_LOCATION string = location
output AZURE_CONTAINER_REGISTRY_ENDPOINT string = resources.outputs.registryLoginServer
output AZURE_RESOURCE_GROUP string = rg.name
output COSMOS_ACCOUNT string = resources.outputs.cosmosAccountName
output COSMOS_ENDPOINT string = resources.outputs.cosmosEndpoint
output COSMOS_DATABASE string = resources.outputs.cosmosDatabaseName
output REDIS_HOST string = resources.outputs.redisHost
output FUNC_APP_NAME string = resources.outputs.funcAppName
output SERVICE_WEB_URI string = resources.outputs.webUri
