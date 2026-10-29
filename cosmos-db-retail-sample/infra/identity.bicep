@description('Location for the identities.')
param location string
param tags object
param resourceToken string

// The web app's identity. It gets the Cosmos DB Built-in Data Contributor role
// (data plane only) and a Redis access policy assignment.
resource appIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2024-11-30' = {
  name: 'retail-id-${resourceToken}'
  location: location
  tags: tags
}

// The function app's identity. The change feed triggers read Azure Cosmos DB and
// write checkpoints to the leases container with the same data-plane role.
resource funcIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2024-11-30' = {
  name: 'retail-func-id-${resourceToken}'
  location: location
  tags: tags
}

output id string = appIdentity.id
output principalId string = appIdentity.properties.principalId
output clientId string = appIdentity.properties.clientId
output name string = appIdentity.name

output funcId string = funcIdentity.id
output funcPrincipalId string = funcIdentity.properties.principalId
output funcClientId string = funcIdentity.properties.clientId
output funcName string = funcIdentity.name
