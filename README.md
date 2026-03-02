# Dagster Cloud Agent for Azure Container Apps

**Deploy Dagster+ hybrid agents on Azure Container Apps with automatic code server management.**

This repository provides a complete solution for running Dagster+ on Azure Container Apps, including:
- ✅ Custom agent that automatically creates code servers and run workers on ACA
- ✅ Ready-to-deploy ARM and Bicep templates
- ✅ Secure secrets management via Azure Key Vault
- ✅ Production-ready networking with VNet integration and hardened NSG egress
- ✅ Enterprise features: resource locks, KV audit logging, Azure Monitor alerts, minimal-privilege RBAC
- ✅ US and EU region support

---

## 🚀 Quick Start

### Step 1: Clone the Repository

```bash
git clone https://github.com/eric-thomas-dagster/aca-agent.git
cd aca-agent
```

### Step 2: Choose Your Image Option

**Option A: Use Pre-Built Image (Fastest)**
```bash
# Use the ready-to-deploy image
IMAGE_URL="ghcr.io/eric-thomas-dagster/dagster-aca-agent:latest"
```

**Option B: Build Your Own**
```bash
# Authenticate with GitHub Container Registry
echo YOUR_GITHUB_TOKEN | docker login ghcr.io -u YOUR_USERNAME --password-stdin

# Build and push
docker build -t dagster-aca-agent:latest .
docker tag dagster-aca-agent:latest ghcr.io/YOUR_USERNAME/dagster-aca-agent:latest
docker push ghcr.io/YOUR_USERNAME/dagster-aca-agent:latest
```

### Step 3: Deploy to Azure

**Option A: Azure Portal (No CLI Required)**
- Follow the complete step-by-step guide in **[QUICKSTART.md](QUICKSTART.md)**
- Takes ~10 minutes
- Just paste ARM template and fill in a form

**Option B: Azure CLI**
```bash
# (Recommended) Deploy the minimal-privilege custom role once per subscription:
ROLE_ID=$(az deployment sub create \
  --location eastus \
  --template-file infra/arm/aca-agent-role.json \
  --query properties.outputs.roleDefinitionId.value -o tsv)

# Deploy the full stack:
az deployment group create \
  --resource-group dagster-demo-rg \
  --template-file infra/arm/full-stack-template.json \
  --parameters \
    agentImage=ghcr.io/eric-thomas-dagster/dagster-aca-agent:latest \
    keyVaultName=dagster-kv-12345 \
    dagsterCloudApiTokenSecretName=DAGSTER-AGENT-TOKEN \
    dagsterCloudApiToken="YOUR_TOKEN_HERE" \
    agentRoleDefinitionId="$ROLE_ID"
    # dagsterRegion=eu   # uncomment for EU region
```

---

## 📁 Project Structure

```
├── app/
│   ├── aca_launcher.py       # AcaUserCodeLauncher + AcaRunLauncher
│   ├── dagster.yaml          # Agent configuration
│   └── entrypoint.py         # Fetches Key Vault secrets, starts agent
├── infra/
│   ├── bicep/
│   │   └── full-stack.bicep  # Complete infrastructure (Bicep)
│   └── arm/
│       ├── full-stack-template.json  # Complete infrastructure (ARM)
│       ├── aca-agent-role.json       # Minimal-privilege custom role (subscription scope)
│       └── ui-definition.json        # Azure Portal parameter groups
├── Dockerfile                # Builds custom agent image
├── requirements.txt          # Python dependencies
├── QUICKSTART.md            # Complete deployment guide
├── SALES_GUIDE.md           # Sales positioning and customer FAQ
└── ARCHITECTURE.md          # Technical deep dive

```

---

## 🏗️ Architecture

**Components:**
- **Agent (ACA)**: Runs 24/7, maintains connection to Dagster Cloud (~$20/month)
- **Code Servers (ACA)**: Automatically created by agent, one per code location (~$20/month each)
- **Run Workers (ACA)**: Ephemeral containers created per job execution, scale to zero after completion

**vs. AKS:** 53% cost savings with no cluster management overhead!

**Key Features:**
- Custom `AcaUserCodeLauncher` creates code servers in the same Container Apps Environment
- Custom `AcaRunLauncher` creates ephemeral run workers per job; background thread cleans up completed workers to stay under the 200-app environment limit
- Managed identity for secure Azure resource access (no stored credentials)
- Key Vault for secrets; audit logs shipped to Log Analytics
- US and EU Dagster+ regions supported; override escape hatch for future regions

---

## 📦 Code Location Requirements

Your Dagster code locations (user code) must include both `dagster` and `dagster-cloud` with matching versions:

```toml
# pyproject.toml
dependencies = [
    "dagster==1.12.6",
    "dagster-cloud==1.12.6",
    # ... your other dependencies
]
```

**Why both?**
- `dagster`: Core framework for defining jobs and assets
- `dagster-cloud`: Required for run execution (GraphQL storage, instance config)

The versions should match the agent base image version (currently `1.12.6`).

---

## 🔒 Security

- Secrets stored in Azure Key Vault — never in code, env var values, or deployment history
- Managed identity for all Azure API calls (no stored credentials)
- VNet integration with service-tag-based NSG egress rules and a DenyAll catch-all
- Optional Key Vault private endpoint (disables public access entirely)
- Minimal-privilege custom RBAC role (deploy `infra/arm/aca-agent-role.json` first); falls back to Contributor if not supplied
- CanNotDelete resource locks on Key Vault and managed identity (on by default)
- Key Vault audit logs shipped to Log Analytics (always enabled)
- Optional Azure Monitor alerts for agent health and Key Vault failures
- Optional NAT Gateway for static outbound IP

See [ARCHITECTURE.md](ARCHITECTURE.md) for the full security model.

---

## 📊 Cost Estimate

**Example: 2 agent replicas + 3 code locations**
- Agent: ~$40/month (2 × 0.25 vCPU, 1 GiB RAM — default HA configuration)
- Code Servers: ~$60/month (3 × 0.5 vCPU, 1 GiB RAM each)
- Run Workers: ~$0 when idle (scale to zero between runs)
- **Total: ~$100/month**

**vs. AKS minimum (~$170/month):** ~40% savings with no cluster management overhead.

See [ARCHITECTURE.md](ARCHITECTURE.md) for the full cost model and optimization tips.

---

## 📚 Documentation

- **[QUICKSTART.md](QUICKSTART.md)** - Complete A-Z deployment guide (start here!)
- **[SALES_GUIDE.md](SALES_GUIDE.md)** - Sales positioning, customer conversations, demos
- **[ARCHITECTURE.md](ARCHITECTURE.md)** - Technical architecture, cost model, monitoring
- **[infra/README.md](infra/README.md)** - Template documentation

---

## 🤝 Contributing

This is a community-maintained solution. Contributions welcome!

---

## 📞 Support

- **Dagster Cloud Docs**: https://docs.dagster.io/dagster-cloud
- **Dagster Slack**: https://dagster.io/slack
- **Azure Container Apps Docs**: https://learn.microsoft.com/azure/container-apps

---

## ⚖️ License

MIT License - See LICENSE file for details
