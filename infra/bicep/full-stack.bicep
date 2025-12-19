param location string = resourceGroup().location
@metadata({
  displayName: 'Container Apps Environment',
  description: 'Name for the Container Apps managed environment.',
  group: 'Configuration'
})
param environmentName string = 'dagster-aca-env'
@metadata({
  displayName: 'Log Analytics Workspace',
  description: 'Name of the Log Analytics workspace for Container Apps logs.',
  group: 'Configuration'
})
param logAnalyticsName string = 'dagster-logs'
@metadata({ displayName: 'Virtual Network', description: 'Name of the VNet to create or use.', group: 'Network' })
param vnetName string = 'dagster-vnet'
param vnetPrefix string = '10.1.0.0/16'
param subnetName string = 'aca-subnet'
param subnetPrefix string = '10.1.0.0/23'
@metadata({ displayName: 'Managed Identity', description: 'User-assigned managed identity the agent will use.', group: 'Configuration' })
param managedIdentityName string = 'dagster-agent-identity'
@metadata({ displayName: 'Key Vault', description: 'Name for the Azure Key Vault used to store secrets.', group: 'Secrets' })
param keyVaultName string = 'dagster-kv'
@metadata({ displayName: 'Container App Name', description: 'Name of the Container App that will run the agent.', group: 'Configuration' })
param containerAppName string = 'dagster-aca-agent'
@metadata({ displayName: 'Agent Image', description: 'Docker image URL for the custom Dagster agent with ACA launcher. Example: ghcr.io/username/dagster-aca-agent:latest', group: 'Configuration' })
param agentImage string
param enableNatGateway bool = false
param additionalRoleAssignments array = []
@metadata({ displayName: 'Additional Key Vault Secrets', description: 'List of additional secret names to fetch at container startup (beyond the required token secret).', group: 'Secrets' })
param keyVaultSecretNames array = []
@metadata({ displayName: 'Dagster Deployment (plaintext)', description: 'Optional plaintext deployment name; set this OR supply a secret-name mapping.', group: 'Configuration' })
param dagsterDeploymentName string = ''
@metadata({ displayName: 'Dagster Organization (plaintext)', description: 'Optional plaintext organization id; set this OR supply a secret-name mapping.', group: 'Configuration' })
param dagsterOrgId string = ''
@metadata({ displayName: 'Dagster Deployment (Key Vault secret)', description: 'Optional Key Vault secret name that contains the deployment name. If provided, the secret will be fetched and put into env var DAGSTER_CLOUD_DEPLOYMENT_NAME.', group: 'Secrets' })
param dagsterDeploymentNameSecretName string = ''
@metadata({ displayName: 'Dagster Organization (Key Vault secret)', description: 'Optional Key Vault secret name that contains the org id. If provided, the secret will be fetched and put into env var DAGSTER_CLOUD_ORG_ID.', group: 'Secrets' })
param dagsterOrgIdSecretName string = ''
@metadata({ displayName: 'Agent Token (Key Vault secret)', description: 'Key Vault secret name for the Dagster agent token (required).', group: 'Secrets' })
param dagsterCloudApiTokenSecretName string
@secure()
@metadata({ displayName: 'Agent Token (value)', description: 'The actual Dagster Cloud agent token value (secure parameter).', group: 'Secrets' })
param dagsterCloudApiToken string
@secure()
@metadata({ displayName: 'Deployment Name (value)', description: 'Optional deployment name value to store in Key Vault (if dagsterDeploymentNameSecretName is provided).', group: 'Secrets' })
param dagsterDeploymentNameSecretValue string = ''
@secure()
@metadata({ displayName: 'Organization ID (value)', description: 'Optional organization ID value to store in Key Vault (if dagsterOrgIdSecretName is provided).', group: 'Secrets' })
param dagsterOrgIdSecretValue string = ''
@metadata({ displayName: 'Agent vCPU', description: 'vCPU for the agent container (use Azure-native fractional CPUs, e.g. 0.25, 0.5, 1).', group: 'Compute' })
param agentCpu number = 0.25
@metadata({ displayName: 'Agent Memory', description: 'Memory for the agent container expressed in Gi/Mi (e.g. \'1.0Gi\').', group: 'Compute' })
param agentMemory string = '1.0Gi'
@metadata({ displayName: 'Num Replicas', description: 'Number of identical agent replicas to keep running (1-5).', group: 'Compute' })
param numReplicas int = 1
@metadata({ displayName: 'Enable Agent Metrics', description: 'Allow the agent to send metrics to Dagster Cloud.', group: 'Monitoring' })
param agentMetricsEnabled bool = false
@metadata({ displayName: 'Enable Code Server Metrics', description: 'Allow code server metrics to be reported to Dagster Cloud.', group: 'Monitoring' })
param codeServerMetricsEnabled bool = false
@metadata({ displayName: 'Zero Downtime Deploys', description: 'When true, Container Apps will keep old revisions running until the new one is healthy.', group: 'Deployment' })
param enableZeroDowntimeDeploys bool = false
@metadata({ displayName: 'ACR Resource ID', description: 'Optional: Resource ID of Azure Container Registry to grant pull access. Example: /subscriptions/{sub}/resourceGroups/{rg}/providers/Microsoft.ContainerRegistry/registries/{name}', group: 'Configuration' })
param acrResourceId string = ''

resource vnet 'Microsoft.Network/virtualNetworks@2020-11-01' = {
  name: vnetName
  location: location
  properties: {
    addressSpace: { addressPrefixes: [vnetPrefix] }
  }
}

resource logAnalytics 'Microsoft.OperationalInsights/workspaces@2020-08-01' = {
  name: logAnalyticsName
  location: location
}

resource identity 'Microsoft.ManagedIdentity/userAssignedIdentities@2018-11-30' = {
  name: managedIdentityName
  location: location
}

resource keyVault 'Microsoft.KeyVault/vaults@2019-09-01' = {
  name: keyVaultName
  location: location
  properties: {
    sku: { family: 'A', name: 'standard' }
    tenantId: subscription().tenantId
    accessPolicies: [
      {
        tenantId: subscription().tenantId
        objectId: reference(identity.id, '2018-11-30').principalId
        permissions: { secrets: [ 'get', 'list' ] }
      }
    ]
  }
}

// Create secrets in Key Vault
resource agentTokenSecret 'Microsoft.KeyVault/vaults/secrets@2019-09-01' = {
  name: dagsterCloudApiTokenSecretName
  parent: keyVault
  properties: {
    value: dagsterCloudApiToken
  }
}

resource deploymentNameSecret 'Microsoft.KeyVault/vaults/secrets@2019-09-01' = if (dagsterDeploymentNameSecretName != '' && dagsterDeploymentNameSecretValue != '') {
  name: dagsterDeploymentNameSecretName
  parent: keyVault
  properties: {
    value: dagsterDeploymentNameSecretValue
  }
}

resource orgIdSecret 'Microsoft.KeyVault/vaults/secrets@2019-09-01' = if (dagsterOrgIdSecretName != '' && dagsterOrgIdSecretValue != '') {
  name: dagsterOrgIdSecretName
  parent: keyVault
  properties: {
    value: dagsterOrgIdSecretValue
  }
}

resource env 'Microsoft.App/managedEnvironments@2022-03-01' = {
  name: environmentName
  location: location
  dependsOn: [ logAnalytics, subnet ]
  properties: {
    appLogsConfiguration: {
      destination: 'log-analytics'
      logAnalyticsConfiguration: {
        customerId: logAnalytics.properties.customerId
        sharedKey: listKeys(logAnalytics.id, '2020-08-01').primarySharedKey
      }
    }
    vnetConfiguration: { infrastructureSubnetResourceId: subnet.id }
  }
}

// optional NAT and public IP
resource natPip 'Microsoft.Network/publicIPAddresses@2020-11-01' = if (enableNatGateway) {
  name: '${vnetName}-nat-pip'
  location: location
  properties: { publicIPAllocationMethod: 'Static' }
  sku: { name: 'Standard' }
}

resource natGw 'Microsoft.Network/natGateways@2020-11-01' = if (enableNatGateway) {
  name: '${vnetName}-natgw'
  location: location
  dependsOn: [ natPip ]
  properties: { publicIpAddresses: [ { id: natPip.id } ] }
}

resource nsg 'Microsoft.Network/networkSecurityGroups@2020-11-01' = {
  name: '${vnetName}-nsg'
  location: location
  properties: {
    securityRules: [
      {
        name: 'AllowIntraSubnet'
        properties: {
          protocol: '*'
          sourcePortRange: '*'
          destinationPortRange: '*'
          sourceAddressPrefix: subnetPrefix
          destinationAddressPrefix: subnetPrefix
          access: 'Allow'
          direction: 'Inbound'
          priority: 100
        }
      }
      {
        name: 'AllowOutbound'
        properties: {
          protocol: '*'
          sourcePortRange: '*'
          destinationPortRange: '*'
          sourceAddressPrefix: '*'
          destinationAddressPrefix: '*'
          access: 'Allow'
          direction: 'Outbound'
          priority: 100
        }
      }
    ]
  }
}

// create subnet separately so we can attach nat gateway and nsg
resource subnet 'Microsoft.Network/virtualNetworks/subnets@2020-11-01' = {
  name: '${vnetName}/${subnetName}'
  parent: vnet
  properties: {
    addressPrefix: subnetPrefix
    networkSecurityGroup: { id: nsg.id }
    natGateway: enableNatGateway ? { id: natGw.id } : null
    delegations: [
      {
        name: 'Microsoft.App.environments'
        properties: {
          serviceName: 'Microsoft.App/environments'
        }
      }
    ]
  }
}

resource containerApp 'Microsoft.App/containerApps@2022-03-01' = {
  name: containerAppName
  location: location
  dependsOn: [ agentTokenSecret, deploymentNameSecret, orgIdSecret ]
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: {
      '${identity.id}': {}
    }
  }
  properties: {
    managedEnvironmentId: env.id
    configuration: { activeRevisionsMode: enableZeroDowntimeDeploys ? 'Multiple' : 'Single', secrets: [] }
    template: {
      containers: [
        {
          name: 'dagster-agent'
          image: agentImage
          resources: { cpu: agentCpu, memory: agentMemory }
          env: [
              { name: 'AGENT_NAME', value: containerAppName }
              { name: 'DAGSTER_CLOUD_URL', value: 'https://dagster.cloud' }
              { name: 'KEY_VAULT_URI', value: 'https://${keyVaultName}.vault.azure.net/' }
              { name: 'KEY_VAULT_SECRET_NAMES', value: join(concat([format('{0}:DAGSTER_CLOUD_API_TOKEN', dagsterCloudApiTokenSecretName)], keyVaultSecretNames, dagsterDeploymentNameSecretName != '' ? [ format('{0}:DAGSTER_CLOUD_DEPLOYMENT_NAME', dagsterDeploymentNameSecretName) ] : [], dagsterOrgIdSecretName != '' ? [ format('{0}:DAGSTER_CLOUD_ORG_ID', dagsterOrgIdSecretName) ] : []), ',') }
              { name: 'DAGSTER_CLOUD_DEPLOYMENT_NAME', value: dagsterDeploymentName }
              { name: 'DAGSTER_CLOUD_ORG_ID', value: dagsterOrgId }
              { name: 'AGENT_METRICS_ENABLED', value: toLower(string(agentMetricsEnabled)) }
              { name: 'CODE_SERVER_METRICS_ENABLED', value: toLower(string(codeServerMetricsEnabled)) }
              // ACA Code Server Launcher configuration
              { name: 'AZURE_SUBSCRIPTION_ID', value: subscription().subscriptionId }
              { name: 'AGENT_RESOURCE_GROUP', value: resourceGroup().name }
              { name: 'ENVIRONMENT_NAME', value: environmentName }
              { name: 'AZURE_LOCATION', value: location }
              // Managed Identity configuration for Azure SDK authentication
              { name: 'AZURE_CLIENT_ID', value: reference(identity.id, '2018-11-30').clientId }
              { name: 'AZURE_TENANT_ID', value: subscription().tenantId }
              // Code server identity - reuses agent identity for simplicity
              { name: 'CODE_SERVER_IDENTITY_ID', value: identity.id }
            ]
        }
      ]
      scale: { minReplicas: numReplicas, maxReplicas: numReplicas }
    }
  }
}

// role assignments
var assignments = additionalRoleAssignments
resource roleAssigns 'Microsoft.Authorization/roleAssignments@2020-04-01-preview' = [for (assignment, i) in assignments: {
  name: guid(subscription().id, resourceGroup().name, managedIdentityName, i)
  properties: {
    roleDefinitionId: assignment.roleDefinitionId
    principalId: reference(identity.id, '2018-11-30').principalId
    principalType: 'ServicePrincipal'
  }
}]

// Grant Contributor role to agent identity on the resource group
// This allows the agent to create and manage Container Apps for code servers
resource contributorRoleAssignment 'Microsoft.Authorization/roleAssignments@2020-04-01-preview' = {
  name: guid(subscription().id, resourceGroup().name, managedIdentityName, 'Contributor')
  scope: resourceGroup()
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', 'b24988ac-6180-42a0-ab88-20f7382dd24c')
    principalId: reference(identity.id, '2018-11-30').principalId
    principalType: 'ServicePrincipal'
  }
}

// NOTE: ACR Access
// If using ACR, grant AcrPull role to the agent identity after deployment:
//   IDENTITY_ID=$(az deployment group show -g <rg> -n <deployment> --query properties.outputs.agentIdentityPrincipalId.value -o tsv)
//   az role assignment create --assignee $IDENTITY_ID --role AcrPull --scope <acrResourceId>
//
// (Role assignment not included in template because it requires permissions on the ACR's resource group)

// NOTE: Code servers are deployed as Container Apps in the SAME environment as the agent.
// - Agent identity: Has Contributor role to create/manage Container Apps + needs AcrPull for images
// - Code servers: Reuse the agent identity (assigned via CODE_SERVER_IDENTITY_ID)

output containerAppResourceId string = containerApp.id
output managedEnvironmentId string = env.id
output environmentName string = environmentName
output keyVaultUri string = 'https://${keyVaultName}.vault.azure.net/'
output agentIdentityResourceId string = identity.id
output agentIdentityPrincipalId string = reference(identity.id, '2018-11-30').principalId
output subnetResourceId string = subnet.id
