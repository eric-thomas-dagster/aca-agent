param location string = resourceGroup().location
param environmentName string = 'dagster-aca-env'
param logAnalyticsName string = 'dagster-logs-${uniqueString(resourceGroup().id)}'

resource logAnalytics 'Microsoft.OperationalInsights/workspaces@2020-08-01' = {
  name: logAnalyticsName
  location: location
  properties: {}
}

resource containerEnv 'Microsoft.App/managedEnvironments@2022-03-01' = {
  name: environmentName
  location: location
  properties: {
    appLogsConfiguration: {
      destination: 'log-analytics'
      logAnalyticsConfiguration: {
        customerId: logAnalytics.properties.customerId
        sharedKey: listKeys(logAnalytics.id, '2020-08-01').primarySharedKey
      }
    }
  }
}

output environmentName string = containerEnv.name
output logAnalyticsWorkspaceId string = logAnalytics.id
