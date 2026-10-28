@description('Location for the identities.')
param location string
param tags object
param resourceToken string

// The web app's identity. It is the SQL server's Microsoft Entra admin so it can
// create the schema, enable change tracking, and grant the function identity access.
resource appIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2024-11-30' = {
  name: 'retail-id-${resourceToken}'
  location: location
  tags: tags
}

// The function app's identity. It gets only the permissions the SQL trigger needs.
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
