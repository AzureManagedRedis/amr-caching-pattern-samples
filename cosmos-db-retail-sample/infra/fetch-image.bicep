// Returns the image the container app is running. When the app already exists,
// resources.bicep uses this image instead of the placeholder, so `azd provision`
// keeps the image that `azd deploy` set. Reading the app in a separate module keeps
// that lookup apart from the app's own declaration; an inline `existing` reference
// works too.
param name string
param exists bool

resource app 'Microsoft.App/containerApps@2026-01-01' existing = if (exists) {
  name: name
}

#disable-next-line BCP318
output image string = exists ? app.properties.template.containers[0].image : ''
