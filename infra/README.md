# Infra helpers

This folder contains helper docs and scripts for deploying the `full-stack-template.json` ARM template for the Dagster Cloud Agent on Azure Container Apps.

Files
- `full-stack-template.json` — main ARM template (already in repo).
- `ui-definition.json` — UI definition used to group parameters in the Azure Portal.
- `publish-template-spec.sh` — helper script to publish the template + UI definition as an Azure Template Spec.

Quick CLI deploy (recommended for automation)

1. Ensure you have the Azure CLI installed and logged in (`az login`).
2. Create the required Key Vault secrets (example):

```bash
# create a Key Vault (or reuse existing)
az group create -n my-rg -l eastus
az keyvault create -n my-kv -g my-rg -l eastus

# add secrets: agent token, optional deployment/org names
az keyvault secret set --vault-name my-kv --name DAGSTER_CLOUD_API_TOKEN --value "<AGENT_TOKEN>"
az keyvault secret set --vault-name my-kv --name DAGSTER_DEPLOYMENT_NAME --value "<DEPLOYMENT_NAME>"
az keyvault secret set --vault-name my-kv --name DAGSTER_ORG_ID --value "<ORG_ID>"
```

3. Run the provided deploy script (example using secret names):

```bash
RESOURCE_GROUP=my-rg LOCATION=eastus \
DAGSTER_DEPLOYMENT_NAME_SECRET_NAME=DAGSTER_DEPLOYMENT_NAME \
DAGSTER_ORG_ID_SECRET_NAME=DAGSTER_ORG_ID \
DAGSTER_TOKEN_SECRET_NAME=DAGSTER_CLOUD_API_TOKEN \
AGENT_CPU=0.5 AGENT_MEMORY=1.0Gi NUM_REPLICAS=1 \
./infra/deploy-arm-full.sh
```

Using the Azure Portal with the UI Definition

- In the Azure Portal, search for "Template deployment" and choose "Deploy a custom template".
- Load the `full-stack-template.json` contents into the editor.
- Open the UI Definition section and paste the contents of `infra/arm/ui-definition.json`.
- Proceed through the grouped parameter pages to deploy.

Publishing a Template Spec (for reuse in the portal)

You can publish the ARM template and UI definition as an Azure Template Spec which makes the template available as a reusable artifact in your subscription.

Use the helper script shipped with this repo:

```bash
# Example: publish templatespec to resource group `my-rg` with name `dagster-agent-template` and version `1.0.0`
./infra/publish-template-spec.sh -g my-rg -n dagster-agent-template -v 1.0.0 -l eastus
```

The script uses `az templatespec create` under the hood. After publishing, you (and others in the subscription) can create resources from the Template Spec in the Azure portal by selecting the Template Spec as the deployment source.

Notes and tips
- The template uses Azure-native compute units: fractional vCPU (`agentCpu`, e.g. `0.25`) and memory strings like `1.0Gi`.
- Secrets are read from Key Vault at container startup using the user-assigned managed identity and the entrypoint helper in the container image.
- The deploy script enforces that the agent token Key Vault secret name is provided and requires either plaintext deployment/org params or secret-name mappings.

If you'd like, I can also add an `az pipelines` or GitHub Actions example to automate populating Key Vault and publishing the Template Spec in CI.
