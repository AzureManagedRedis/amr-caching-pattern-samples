targetScope = 'subscription'

@minLength(1)
@maxLength(64)
@description('Name of the azd environment; used to derive resource names.')
param environmentName string

@minLength(1)
@description('Primary location for all resources.')
param location string

@description('Container image for the web service. azd sets this after building.')
param webImageName string = ''

var tags = { 'azd-env-name': environmentName }
var resourceToken = toLower(uniqueString(subscription().id, environmentName, location))

resource rg 'Microsoft.Resources/resourceGroups@2025-04-01' = {
  name: 'rg-${environmentName}'
  location: location
  tags: tags
}

// The identity is provisioned first so its principal ID is available as a
// parameter to the resources module (a resource's runtime principalId cannot be
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
    webImageName: webImageName
    identityId: identity.outputs.id
    identityPrincipalId: identity.outputs.principalId
    identityClientId: identity.outputs.clientId
    identityName: identity.outputs.name
  }
}

output AZURE_LOCATION string = location
output AZURE_CONTAINER_REGISTRY_ENDPOINT string = resources.outputs.registryLoginServer
output POSTGRES_HOST string = resources.outputs.postgresHost
output POSTGRES_USER string = identity.outputs.name
output REDIS_HOST string = resources.outputs.redisHost
output SERVICE_WEB_URI string = resources.outputs.webUri
