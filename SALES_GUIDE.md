# Sales Engineer Guide: Dagster Cloud Agent on Azure Container Apps

This guide helps you demonstrate and deploy the Dagster Cloud Agent on Azure Container Apps for prospects and customers.

## 🚀 **VM-FREE MANAGED CONTAINERS ON AZURE**

This is a **100% VM-free Azure-native** Dagster Cloud deployment using Container Apps:

### Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│ Customer's Azure Subscription (VM-Free)                         │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  Container Apps Environment                                     │
│  ┌────────────────────────────────────────────────────────────┐│
│  │                                                             ││
│  │  ┌──────────────────┐         ┌────────────────────────┐  ││
│  │  │ Agent (ACA)      │────────>│  Code Server 1 (ACA)   │  ││
│  │  │ Always: 1 replica│ Deploy  │  Always: 1 replica     │  ││
│  │  │ ~$20/month       │         │  ~$20/month            │  ││
│  │  └──────────────────┘         └────────────────────────┘  ││
│  │                                                             ││
│  │                                ┌────────────────────────┐  ││
│  │                                │  Code Server 2 (ACA)   │  ││
│  │                                │  Always: 1 replica     │  ││
│  │                                │  ~$20/month            │  ││
│  │                                └────────────────────────┘  ││
│  │                                                             ││
│  └────────────────────────────────────────────────────────────┘│
│           │                                 │                   │
│           │ Uses Managed Identity           │ Executes Jobs    │
│           v                                 v                   │
│  ┌──────────────────────┐         ┌────────────────────────┐  │
│  │   Azure Key Vault    │         │  Customer Data Sources │  │
│  │   (Secrets)          │         │  (Storage, DBs, APIs)  │  │
│  └──────────────────────┘         └────────────────────────┘  │
│                                                                 │
│  VNet Integration → Private Networking (Optional)              │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
                            │
                            │ Control Plane Only
                            v
                  ┌────────────────────┐
                  │  Dagster Cloud     │
                  │  (Metadata Only)   │
                  └────────────────────┘
```

### Key Differentiators

✅ **No Kubernetes** - No AKS cluster, no k8s expertise required
✅ **No VMs to Manage** - Azure manages all infrastructure
✅ **50% Cost Savings** - $80/month vs $170+/month for AKS (3 code locations)
✅ **100% Azure** - All compute in customer's subscription
✅ **Fully Managed** - Azure handles scaling, patching, monitoring

### Cost Comparison (3 Code Locations)

| Component | Managed Containers (ACA) | Traditional (AKS) |
|-----------|---------------------------|-------------------|
| Control Plane | Included | ~$70/month |
| Agent | ~$20/month (1 ACA) | ~$50/month (node share) |
| Code Servers | ~$60/month (3 ACAs) | ~$50+/month (node share) |
| **Total** | **~$80/month** | **~$170/month** |
| **Savings** | **53% cheaper** | Baseline |

## Overview

This solution deploys a fully managed Dagster+ agent on Azure with:
- **VM-free architecture** - No VMs to patch, upgrade, or manage
- **Container Apps platform** - Agent and code servers on same platform
- **Enterprise security** - Azure Key Vault for secrets, Managed Identity, VNet integration
- **Zero-downtime deploys** - Built-in blue-green deployments for code updates
- **Production-ready** - High availability, auto-healing, integrated monitoring
- **Azure-native** - Uses Azure Container Apps for all compute

## Deployment Options (Customer Decision Tree)

### Option 1: Azure Portal "Deploy to Azure" Button (Easiest for customers)
**Best for:** Quick demos, POCs, customers who prefer GUI

### Option 2: Azure Template Spec (Reusable catalog item)
**Best for:** Customers with standardized deployment processes, multiple deployments

### Option 3: Azure CLI / Automation (Most flexible)
**Best for:** Customers with existing CI/CD pipelines, infrastructure-as-code practices

---

## Option 1: Azure Portal Deployment (Click-to-Deploy Experience)

### What You Need Before the Demo:
1. Azure subscription with Contributor access
2. Dagster Cloud organization and deployment
3. Dagster Cloud agent token (get from Dagster Cloud UI: Settings → Agents → Create Agent Token)

### Live Demo Steps (15 minutes):

#### Step 1: Prepare Secrets (5 min)
Before deployment, create a Key Vault and add secrets:

```bash
# Create resource group and Key Vault
az group create -n dagster-demo-rg -l eastus
az keyvault create -n dagster-demo-kv -g dagster-demo-rg -l eastus

# Add required secrets
az keyvault secret set --vault-name dagster-demo-kv --name DAGSTER_AGENT_TOKEN --value "YOUR_AGENT_TOKEN_HERE"
az keyvault secret set --vault-name dagster-demo-kv --name DAGSTER_DEPLOYMENT_NAME --value "prod"
az keyvault secret set --vault-name dagster-demo-kv --name DAGSTER_ORG_ID --value "YOUR_ORG_ID_HERE"
```

**Pro tip:** Get these values from:
- Agent Token: Dagster Cloud → Settings → Agents → Create Agent Token
- Org ID: Visible in Dagster Cloud URL (dagster.cloud/YOUR_ORG_ID)
- Deployment Name: Usually "prod" or customer-specific name

#### Step 2: Deploy via Azure Portal (5 min)

1. Navigate to Azure Portal → Search "Deploy a custom template"
2. Click "Build your own template in the editor"
3. Paste contents of `infra/arm/full-stack-template.json`
4. Click "Add UI definition" → Paste contents of `infra/arm/ui-definition.json`
5. Click "Save"

#### Step 3: Fill in Parameters (3 min)

**Configuration Tab:**
- Location: `eastus` (or customer preference)
- Environment Name: `dagster-aca-env`
- Container App Name: `dagster-agent`

**Secrets Tab:**
- Key Vault Name: `dagster-demo-kv` (the vault you created)
- Agent Token Secret Name: `DAGSTER_AGENT_TOKEN`
- Deployment Name Secret Name: `DAGSTER_DEPLOYMENT_NAME`
- Org ID Secret Name: `DAGSTER_ORG_ID`

**Compute Tab:** (defaults are fine for demo)
- vCPU: `0.25`
- Memory: `1.0Gi`
- Replicas: `1`

**Network Tab:**
- Accept defaults (creates new VNet)
- Optional: Enable NAT Gateway for static outbound IP

#### Step 4: Validate Deployment (2 min)

```bash
# Check Container App status
az containerapp show -n dagster-agent -g dagster-demo-rg --query "properties.runningStatus"

# View logs
az containerapp logs show -n dagster-agent -g dagster-demo-rg --follow
```

Check Dagster Cloud UI → Agents to confirm agent is connected.

---

## Option 2: Azure Template Spec (Customer Self-Service)

### Setup (One-time, 10 minutes):

This creates a reusable template in the customer's Azure subscription that they can deploy multiple times.

#### Step 1: Publish the Template Spec

```bash
# Clone this repo
git clone https://github.com/YOUR_ORG/dagster-cloud-agent-aca.git
cd dagster-cloud-agent-aca

# Publish to customer's subscription
./infra/publish-template-spec.sh \
  -g shared-templates-rg \
  -n dagster-agent-aca \
  -v 1.0.0 \
  -l eastus
```

#### Step 2: Share Template Spec with Customer Team

After publishing, the template appears in Azure Portal under:
- **Deploy a custom template** → **Template specs** → `dagster-agent-aca`

Any user with access to the subscription can deploy it with one click.

### Customer Benefits:
- No need to copy/paste JSON
- Version-controlled deployments
- Consistent across teams
- Can be deployed via Portal or CLI

### Customer Deployment (Self-Service):
```bash
# Deploy from Template Spec
az deployment group create \
  -g dagster-prod-rg \
  --template-spec "/subscriptions/SUBSCRIPTION_ID/resourceGroups/shared-templates-rg/providers/Microsoft.Resources/templateSpecs/dagster-agent-aca/versions/1.0.0" \
  --parameters location=eastus \
    keyVaultName=dagster-prod-kv \
    dagsterCloudApiTokenSecretName=DAGSTER_AGENT_TOKEN
```

---

## Option 3: Azure CLI / Automation (DevOps Teams)

### Prerequisites:
- Azure CLI installed (`az login`)
- Key Vault with secrets configured

### Quick Deploy (10 minutes):

```bash
# 1. Set environment variables
export RESOURCE_GROUP=dagster-prod-rg
export LOCATION=eastus
export DAGSTER_TOKEN_SECRET_NAME=DAGSTER_AGENT_TOKEN
export DAGSTER_DEPLOYMENT_NAME_SECRET_NAME=DAGSTER_DEPLOYMENT_NAME
export DAGSTER_ORG_ID_SECRET_NAME=DAGSTER_ORG_ID

# Optional: Configure sizing
export AGENT_CPU=0.5
export AGENT_MEMORY=2.0Gi
export NUM_REPLICAS=2

# 2. Run deployment script
cd dagster-cloud-agent-aca
./infra/deploy-arm-full.sh

# 3. Verify agent is running
az containerapp logs show -n dagster-aca-agent -g $RESOURCE_GROUP --follow

# 4. (Optional) If using private ACR, assign AcrPull role
# IDENTITY_ID=$(az deployment group show -g $RESOURCE_GROUP -n dagster-aca-full --query properties.outputs.identityPrincipalId.value -o tsv)
# az role assignment create --assignee $IDENTITY_ID --role AcrPull --scope /subscriptions/{sub}/resourceGroups/{acr-rg}/providers/Microsoft.ContainerRegistry/registries/{acr-name}
```

**That's it!** Code servers will be automatically created as Container Apps in the same environment when you deploy code locations.

### Integration with CI/CD:

**GitHub Actions Example:**
```yaml
- name: Deploy Dagster Agent
  run: |
    az login --service-principal -u ${{ secrets.AZURE_CLIENT_ID }} -p ${{ secrets.AZURE_CLIENT_SECRET }} --tenant ${{ secrets.AZURE_TENANT_ID }}

    export RESOURCE_GROUP=dagster-prod-rg
    export DAGSTER_TOKEN_SECRET_NAME=DAGSTER_AGENT_TOKEN
    export DAGSTER_DEPLOYMENT_NAME_SECRET_NAME=DAGSTER_DEPLOYMENT_NAME
    export DAGSTER_ORG_ID_SECRET_NAME=DAGSTER_ORG_ID

    ./infra/deploy-arm-full.sh
```

---

## Common Customer Questions & Answers

### Q: How is this different from deploying on AKS?
**A:** Azure Container Apps is serverless - no Kubernetes cluster to manage, patch, or scale. It's simpler, more cost-effective for small-to-medium workloads, and still production-grade. Use AKS for complex multi-tenant scenarios or when you need full Kubernetes control.

### Q: What's the monthly cost?
**A:** With default settings (0.25 vCPU, 1GB RAM):
- Container Apps: ~$15-20/month
- Log Analytics: ~$5/month
- Key Vault: ~$1/month
- Total: ~$20-25/month

Compare to AKS which starts at $70+/month for the control plane alone.

### Q: Is this production-ready?
**A:** Yes. It includes:
- High availability with multiple replicas
- Zero-downtime deployments
- VNet isolation for security
- Managed Identity for secure credential management
- Azure Monitor integration
- Optional NAT Gateway for static outbound IP

### Q: Can it scale for our workload?
**A:** Azure Container Apps supports:
- Up to 600 concurrent jobs per environment
- Auto-scaling based on HTTP requests, CPU, memory, or custom metrics
- Vertical scaling up to 4 vCPU and 8GB per container
- Horizontal scaling up to 30 replicas (configurable)

For most Dagster workloads, 1-5 agent replicas are sufficient.

### Q: Are the agent and code servers always running?
**A:** Yes! Both the **agent AND code servers are long-lived** - they run 24/7.

**Architecture:**
- **Agent (ACA)**: Always running (`minReplicas: 1`), maintains connection to Dagster Cloud (~$20/month)
- **Code Servers (ACA)**: Also always running (`minReplicas: 1` each), serve Dagster definitions (~$20/month each)

**Why both are always-on:**
- Agent must stay connected to receive deployment requests
- Code servers must stay running to serve definitions and execute jobs quickly
- When code changes, code servers do blue-green deployments (not recreation)
- This is NOT "scale-to-zero serverless" - it's "VM-free managed containers"

**Cost breakdown (3 code locations):**
- Agent: ~$20/month (0.25 vCPU, 1GB RAM)
- Code Server 1: ~$20/month (0.5 vCPU, 1GB RAM)
- Code Server 2: ~$20/month (0.5 vCPU, 1GB RAM)
- Code Server 3: ~$20/month (0.5 vCPU, 1GB RAM)
- **Total: ~$80/month**

**High availability:**
- For production, use `numReplicas: 2` for agent redundancy
- Cost: ~$40/month for agent + $60/month for code servers = **$100/month**

**vs. AKS:**
- AKS: $70 control plane + $100+ always-on nodes = $170/month minimum
- ACA: $80/month typical (53% savings!)
- **Key difference:** No VM management, no Kubernetes complexity

### Q: How do code servers work on Azure Container Apps?
**A:** Code servers are deployed as Container Apps (just like the agent) when you deploy code locations to Dagster Cloud.

**Workflow:**
1. You deploy a code location to Dagster Cloud (via CI/CD or CLI)
2. Agent receives notification from Dagster Cloud
3. Agent creates a Container App with your Dagster code image
4. Code server starts and registers with Dagster Cloud
5. Code server stays running to serve definitions and execute jobs
6. When you update code, ACA does blue-green deployment (zero downtime!)

**Benefits:**
- **Same platform**: All on Container Apps (agent + code servers)
- **Zero-downtime updates**: Built-in blue-green deployments
- **Auto-healing**: ACA automatically restarts failed containers
- **Isolation**: Each code location gets its own Container App
- **Integrated monitoring**: All logs in same Log Analytics workspace

**Configuration:**
- Default: 0.5 vCPU, 1.0Gi RAM per code server
- Customize per code location via `container_context`
- Shares same VNet and Container Apps Environment as agent
- Uses same managed identity for secure access

**Monitoring:**
```bash
# List all code servers
az containerapp list -g dagster-rg --query "[?tags.\"dagster-component\"=='code-server'].{Name:name,Status:properties.runningStatus}" -o table

# View code server logs
az containerapp logs show -n dagster-prod-myproject -g dagster-rg --follow

# Check agent logs
az containerapp logs show -n dagster-aca-agent -g dagster-rg --follow
```

### Q: How do we update the agent version?
**A:** Two approaches:
1. **Update container image in deployment**:
   ```bash
   az containerapp update -n dagster-agent -g dagster-rg \
     --image dagster/dagster-cloud-agent:1.5.0
   ```

2. **Re-deploy with new template parameters** (if using enableZeroDowntimeDeploys=true, no downtime)

### Q: Can we use our existing VNet?
**A:** Yes! Use the `existing-vnet-template.json` instead, which accepts a `subnetResourceId` parameter pointing to your existing subnet.

### Q: How do we monitor the agent?
**A:**
- **Azure Portal**: Container Apps → Logs → Application Insights
- **Azure CLI**: `az containerapp logs show -n dagster-agent -g dagster-rg --follow`
- **Dagster Cloud UI**: View agent health and job execution metrics
- **Optional**: Enable agent metrics with `agentMetricsEnabled=true`

---

## Demo Environment Cleanup

After your demo, clean up resources:

```bash
# Delete entire resource group (removes all resources)
az group delete -n dagster-demo-rg --yes --no-wait
```

---

## Pre-Sales Collateral

### Slide Deck Talking Points:
1. **Slide 1 - Problem**: Managing Kubernetes is complex and expensive for data teams
2. **Slide 2 - Solution**: Dagster Cloud + Azure Container Apps = Serverless data orchestration
3. **Slide 3 - Architecture**: Show diagram (VNet, ACA, Key Vault, Dagster Cloud)
4. **Slide 4 - Security**: Managed Identity, Key Vault, VNet isolation, zero credentials in code
5. **Slide 5 - Cost**: 70% less than AKS for typical workloads
6. **Slide 6 - Demo**: Live deployment in 15 minutes

### Customer Success Story Template:
```
"[Company X] deployed Dagster Cloud agents on Azure Container Apps to orchestrate their
data pipelines. Within 2 weeks, they eliminated their Kubernetes overhead, reduced cloud
costs by $2,000/month, and improved deployment velocity by 3x. The serverless architecture
allowed their data engineering team to focus on pipelines, not infrastructure."
```

---

## Technical Validation Checklist

Before handing off to a customer, verify:

- [ ] Agent appears as "Running" in Dagster Cloud UI
- [ ] Container App shows "Running" status in Azure Portal
- [ ] Agent can execute a test job successfully
- [ ] Logs are flowing to Log Analytics workspace
- [ ] Managed Identity has access to Key Vault
- [ ] VNet integration working (if required)
- [ ] Customer's security team approved the architecture

---

## Support & Escalation

**For customers:**
- Dagster Cloud support: support@dagster.io
- Azure support: Azure Portal → Support

**For sales engineers:**
- Internal Slack: #dagster-sales-engineering
- Escalation: solutions-architecture@dagster.io

---

## Quick Reference Card (Print this!)

```
┌─────────────────────────────────────────────────────────────┐
│ DAGSTER CLOUD AGENT - AZURE CONTAINER APPS QUICK DEPLOY    │
├─────────────────────────────────────────────────────────────┤
│ 1. CREATE KEY VAULT & SECRETS                               │
│    az keyvault create -n dagster-kv -g dagster-rg           │
│    az keyvault secret set --vault-name dagster-kv \         │
│      --name DAGSTER_AGENT_TOKEN --value "..."               │
│                                                              │
│ 2. DEPLOY VIA PORTAL                                        │
│    Azure Portal → Custom Template → Load JSON               │
│    Template: infra/arm/full-stack-template.json             │
│    UI Def: infra/arm/ui-definition.json                     │
│                                                              │
│ 3. OR DEPLOY VIA CLI                                        │
│    export RESOURCE_GROUP=dagster-rg                         │
│    export DAGSTER_TOKEN_SECRET_NAME=DAGSTER_AGENT_TOKEN     │
│    export DAGSTER_DEPLOYMENT_NAME_SECRET_NAME=...           │
│    export DAGSTER_ORG_ID_SECRET_NAME=...                    │
│    ./infra/deploy-arm-full.sh                               │
│                                                              │
│ 4. VERIFY                                                   │
│    - Dagster Cloud UI → Agents (should show "Running")      │
│    - Azure Portal → Container Apps → dagster-agent          │
│    - az containerapp logs show -n dagster-agent \           │
│        -g dagster-rg --follow                               │
└─────────────────────────────────────────────────────────────┘
```

---

## Additional Resources

- [Dagster Cloud Documentation](https://docs.dagster.io/cloud)
- [Azure Container Apps Documentation](https://docs.microsoft.com/azure/container-apps/)
- [Architecture Diagram](./docs/architecture-diagram.png) *(create this!)*
- [Video Walkthrough](https://youtu.be/...) *(record this!)*

---

**Last Updated:** 2025-12-12
**Version:** 1.0.0
**Maintained by:** Sales Engineering Team
