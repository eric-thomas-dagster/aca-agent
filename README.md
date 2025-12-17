# Dagster Cloud Agent for Azure Container Apps

**Deploy Dagster+ hybrid agents on Azure Container Apps with automatic code server management.**

This repository provides a complete solution for running Dagster Cloud (Dagster+) on Azure Container Apps, including:
- ✅ Custom agent that automatically creates code servers on ACA
- ✅ Ready-to-deploy ARM and Bicep templates
- ✅ Secure secrets management via Azure Key Vault
- ✅ Production-ready networking with VNet integration

---

## 🚀 Quick Start

### 1. Build and Publish Docker Image

```bash
# Authenticate with GitHub Container Registry
echo YOUR_GITHUB_TOKEN | docker login ghcr.io -u YOUR_GITHUB_USERNAME --password-stdin

# Build and push the custom image
docker build -t dagster-aca-agent:latest .
docker tag dagster-aca-agent:latest ghcr.io/YOUR_GITHUB_USERNAME/dagster-aca-agent:latest
docker push ghcr.io/YOUR_GITHUB_USERNAME/dagster-aca-agent:latest
```

### 2. Deploy to Azure

**Option A: Azure Portal (No CLI Required)**
- Follow the complete step-by-step guide in **[QUICKSTART.md](QUICKSTART.md)**
- Takes ~10 minutes
- Just paste ARM template and fill in a form

**Option B: Azure CLI**
```bash
az deployment group create \
  --resource-group dagster-demo-rg \
  --template-file infra/arm/full-stack-template.json \
  --parameters \
    agentImage=ghcr.io/YOUR_GITHUB_USERNAME/dagster-aca-agent:latest \
    keyVaultName=dagster-kv-12345 \
    dagsterCloudApiTokenSecretName=DAGSTER-AGENT-TOKEN \
    dagsterCloudApiToken="YOUR_TOKEN_HERE"
```

---

## 📁 Project Structure

```
├── app/
│   ├── aca_launcher.py       # Custom ACA code server launcher
│   ├── dagster.yaml          # Agent configuration
│   └── entrypoint.py         # Fetches Key Vault secrets, starts agent
├── infra/
│   ├── bicep/
│   │   └── full-stack.bicep  # Complete infrastructure (Bicep)
│   └── arm/
│       └── full-stack-template.json  # Complete infrastructure (ARM)
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
- **Jobs**: Created as separate Container Apps by code servers, scale to zero after completion

**vs. AKS:** 53% cost savings with no cluster management overhead!

**Key Features:**
- Custom `AcaUserCodeLauncher` creates code servers in the same Container Apps Environment
- Blue-green deployments for zero-downtime updates
- Managed identity for secure Azure resource access
- Key Vault integration for secrets

---

## 🔒 Security

- Secrets stored in Azure Key Vault (never in code or deployment history)
- Managed identity for authentication (no credentials stored)
- VNet integration for private networking
- Optional NAT Gateway for static outbound IP

---

## 📊 Cost Estimate

**Example: 1 agent + 3 code locations**
- Agent: ~$20/month (0.25 vCPU, 1GB RAM)
- Code Servers: ~$60/month (3 × $20/month, 0.5 vCPU, 1GB RAM each)
- **Total: ~$80/month**

**vs. AKS minimum:** $170/month (53% savings!)

Jobs scale to zero automatically (no additional cost when idle).

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
