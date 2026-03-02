// aca-agent-role.bicep
// Deploy at SUBSCRIPTION scope (az deployment sub create ...) before running
// the full-stack template.  Outputs the role definition ID to pass as the
// agentRoleDefinitionId parameter of full-stack.bicep.
//
// Usage:
//   az deployment sub create \
//     --location eastus \
//     --template-file infra/bicep/aca-agent-role.bicep
//
// Then pass the output roleDefinitionId to the full-stack deployment.

targetScope = 'subscription'

resource acaAgentRole 'Microsoft.Authorization/roleDefinitions@2022-04-01' = {
  // Deterministic GUID scoped to this subscription so the role is idempotent.
  name: guid(subscription().id, 'dagster-aca-agent-role')
  properties: {
    roleName: 'Dagster ACA Agent'
    description: 'Minimum permissions for the Dagster Cloud ACA agent to manage code-server Container Apps and assign managed identities to them.'
    type: 'CustomRole'
    assignableScopes: [ subscription().id ]
    permissions: [
      {
        actions: [
          // Container App lifecycle (code servers + run workers)
          'Microsoft.App/containerApps/read'
          'Microsoft.App/containerApps/write'
          'Microsoft.App/containerApps/delete'
          'Microsoft.App/containerApps/revisions/read'
          // Read the managed environment (needed to look up environment ID)
          'Microsoft.App/managedEnvironments/read'
          'Microsoft.App/managedEnvironments/join/action'
          // Assign the user-assigned managed identity to code-server Container Apps
          'Microsoft.ManagedIdentity/userAssignedIdentities/assign/action'
        ]
        notActions: []
      }
    ]
  }
}

output roleDefinitionId string = acaAgentRole.id
