// Returns the image the container app is running, so provisioning can keep it.
// Kept in its own module: reading the app in the same template that declares it
// creates a circular dependency.
param name string
param exists bool

resource app 'Microsoft.App/containerApps@2026-01-01' existing = if (exists) {
  name: name
}

#disable-next-line BCP318
output image string = exists ? app.properties.template.containers[0].image : ''
