# Complete A-Z Quickstart Guide

**For someone who hasn't used Azure in a while and wants to get this deployed quickly.**

## Prerequisites

Before you start, you need:

1. ✅ **Azure subscription** (you have this!)
2. ✅ **Dagster Cloud account** - Sign up at https://dagster.cloud if you don't have one
3. ✅ **Dagster Cloud agent token** - We'll get this in Step 1

That's it! No CLI needed for the portal deployment.

---

## ⚠️ **IMPORTANT: Build Custom Docker Image First**

This deployment uses a **custom Docker image** that includes the Azure Container Apps launcher. You need to build and publish this image before deploying.

**One-time setup (5 minutes):**
1. Build the Docker image (includes ACA launcher code)
2. Push to GitHub Container Registry (free, public)
3. Then proceed with deployment below

**[Jump to Docker Setup Instructions](#docker-setup)**

---

## Choose Your Deployment Path

### 🖱️ **Option A: Azure Portal (Easiest - No CLI Required)**
**Time: 10 minutes**
Just 3 steps: Create resource group, paste ARM template, fill in credentials - done!

### 💻 **Option B: Azure CLI (For automation)**
**Time: 15 minutes**
Install CLI tools, run scripts from terminal

---

# 🐳 DOCKER SETUP (Required First-Time Setup)

Before you can deploy the agent, you need a custom Docker image with the ACA launcher.

## What's in the Custom Image?

This repo includes custom code that the standard Dagster agent doesn't have:
- **`app/aca_launcher.py`** - Creates code servers on Azure Container Apps
- **`app/dagster.yaml`** - Configures agent to use the ACA launcher
- **`app/entrypoint.py`** - Fetches secrets from Azure Key Vault

**⚠️ IMPORTANT:** The official `dagster/dagster-cloud-agent:latest` image will NOT work! It doesn't have the ACA launcher code. You MUST use a custom image.

---

## Choose Your Approach

### Option 1: Use Pre-Built Image (Fastest)
Use the pre-built image maintained by Dagster:
```
ghcr.io/eric-thomas-dagster/dagster-aca-agent:latest
```
**Pros:** Ready to use, no build needed
**Cons:** You're trusting a third-party image

### Option 2: Build Your Own (Recommended for Production)
Build and host your own image for full control.

---

## Step 0: Build and Publish Docker Image (Option 2)

### Prerequisites
- Docker Desktop installed ([download here](https://www.docker.com/products/docker-desktop))
- GitHub account (for Container Registry)

### 0.1 Authenticate with GitHub Container Registry

```bash
# Create a GitHub Personal Access Token (if you don't have one):
# 1. Go to https://github.com/settings/tokens
# 2. Click "Generate new token (classic)"
# 3. Check: write:packages, read:packages, delete:packages
# 4. Copy the token

# Login to ghcr.io
echo YOUR_GITHUB_TOKEN | docker login ghcr.io -u eric-thomas-dagster --password-stdin
```

### 0.2 Build the Image

```bash
# Clone this repo (if you haven't already)
cd dagster-cloud-agent-aca

# Build the image
docker build -t dagster-aca-agent:latest .

# Tag for GitHub Container Registry
# Replace eric-thomas-dagster with your actual GitHub username
docker tag dagster-aca-agent:latest ghcr.io/eric-thomas-dagster/dagster-aca-agent:latest
```

### 0.3 Push to GitHub Container Registry

```bash
# Push the image
docker push ghcr.io/eric-thomas-dagster/dagster-aca-agent:latest

# ✅ Your image is now available at: ghcr.io/eric-thomas-dagster/dagster-aca-agent:latest
```

### 0.4 Make Image Public (Optional but Recommended)

By default, the image is private. To make it public:

1. Go to https://github.com/eric-thomas-dagster?tab=packages
2. Click on **dagster-aca-agent**
3. Click **Package settings**
4. Scroll to **Danger Zone**
5. Click **Change visibility** → **Public**

**Why make it public?**
- Azure can pull it without authentication
- Simpler deployment (no image pull secrets needed)
- It doesn't contain any secrets (those are in Key Vault)

---

## Alternative: Use Azure Container Registry (ACR)

If you prefer to keep everything in Azure, you can use ACR instead:

```bash
# Create Azure Container Registry
az acr create --name mycompanyacr --resource-group dagster-demo-rg --sku Basic

# Login to ACR
az acr login --name mycompanyacr

# Build and push directly to ACR
docker build -t mycompanyacr.azurecr.io/dagster-aca-agent:latest .
docker push mycompanyacr.azurecr.io/dagster-aca-agent:latest

# Your image URL will be: mycompanyacr.azurecr.io/dagster-aca-agent:latest
```

**Note:** If using ACR, you'll need to grant the managed identity `AcrPull` role:
```bash
# Get identity principal ID (after deployment)
IDENTITY_ID=$(az identity show -n dagster-agent-identity -g dagster-demo-rg --query principalId -o tsv)

# Grant AcrPull role
az role assignment create \
  --assignee $IDENTITY_ID \
  --role AcrPull \
  --scope /subscriptions/YOUR_SUB_ID/resourceGroups/dagster-demo-rg/providers/Microsoft.ContainerRegistry/registries/mycompanyacr
```

---

## 📝 Note Your Image URL

You'll need this URL when deploying:
```
ghcr.io/eric-thomas-dagster/dagster-aca-agent:latest
```

**Example:** If your GitHub username is `johndoe`, your image URL is:
```
ghcr.io/johndoe/dagster-aca-agent:latest
```

Save this URL - you'll enter it in the deployment form!

---

# 🖱️ OPTION A: Azure Portal Deployment (Recommended for First Time)

No CLI installation needed! Do everything in your browser.

## Step 1: Get Your Dagster Cloud Credentials

### 1.1 Log into Dagster Cloud
- Go to https://dagster.cloud
- Sign in to your account

### 1.2 Create an Agent Token
1. Click your organization name (top left)
2. Click **Settings** (gear icon)
3. Click **Agents** in the left sidebar
4. Click **Create Agent Token**
5. Name it: `azure-aca-agent`
6. **Copy the token** - you'll need it in Step 3
7. **Important:** Save this token somewhere safe! You can't see it again.

### 1.3 Get Your Organization Details
While you're in Dagster Cloud, note down:
- **Organization ID**: Look at your URL: `https://dagster.cloud/{YOUR_ORG_ID}`
- **Deployment Name**: Usually `prod` (visible in top navigation)

**Example:**
- Token: `agent_abc123xyz789...` (long string)
- Org ID: `mycompany`
- Deployment: `prod`

---

## Step 2: Log into Azure Portal

1. Go to https://portal.azure.com
2. Sign in with your Microsoft account
3. You should see the Azure Portal dashboard

**First time in a while?** Azure might ask you to:
- Verify your identity
- Update payment method
- Accept new terms

---

## Step 3: Create a Resource Group

This is the container that will hold all your Azure resources.

1. In the search bar at top, type: **Resource groups**
2. Click **Create**
3. Fill in:
   - **Subscription**: Select your subscription
   - **Resource group**: `dagster-demo-rg`
   - **Region**: `East US` (or your preferred region)
4. Click **Review + Create** → **Create**

---

## Step 4: Deploy the ARM Template

Now we'll deploy the agent using the ARM template.

### 4.1 Open Custom Deployment

1. In the search bar, type: **Deploy a custom template**
2. Click on **Deploy a custom template** service
3. Click **Build your own template in the editor**

### 4.2 Paste the ARM Template

1. You'll see a JSON editor
2. **Delete all the existing content**
3. Open this file on your computer: `infra/arm/full-stack-template.json`
4. **Copy the entire contents** (Ctrl+A, Ctrl+C or Cmd+A, Cmd+C)
5. **Paste into the Azure editor**
6. Click **Save**

### 4.3 Fill in the Parameters

Now Azure will show you a form to fill in. Here's what to enter:

**Basics:**
- **Subscription**: Your subscription
- **Resource group**: `dagster-demo-rg` (select existing)
- **Region**: `East US`

**Configuration:**
- **Environment Name**: `dagster-aca-env` (leave default)
- **Log Analytics Name**: `dagster-logs` (leave default)
- **Container App Name**: `dagster-aca-agent` (leave default)
- **Managed Identity Name**: `dagster-agent-identity` (leave default)
- **Agent Image**: `ghcr.io/eric-thomas-dagster/dagster-aca-agent:latest` (⚠️ USE YOUR IMAGE URL from Docker setup!)

**Secrets (Secure):**
- **Key Vault Name**: `dagster-demo-kv-12345` (choose a unique name - add random numbers)
- **Dagster Cloud Api Token Secret Name**: `DAGSTER-AGENT-TOKEN` (name for the secret in Key Vault)
- **Dagster Cloud Api Token**: Paste your agent token from Step 1.2 (secure - won't be visible in deployment history)
- **Dagster Deployment Name Secret Name**: `DAGSTER-DEPLOYMENT-NAME`
- **Dagster Deployment Name Secret Value**: `prod` (or your deployment name)
- **Dagster Org Id Secret Name**: `DAGSTER-ORG-ID`
- **Dagster Org Id Secret Value**: Your organization ID from Step 1.3

**Compute:**
- **Agent Cpu**: `0.5` (upgrade from 0.25 for better performance)
- **Agent Memory**: `1.0Gi` (leave default)
- **Num Replicas**: `1` (leave default)

**Monitoring:**
- **Enable Agent Metrics**: Leave unchecked
- **Enable Code Server Metrics**: Leave unchecked

**Network:**
- **Enable Nat Gateway**: Leave unchecked
- Leave other network fields as defaults

### 4.4 Deploy!

1. Click **Review + Create**
2. Azure will validate the template (takes ~30 seconds)
3. If validation passes, click **Create**
4. **Wait 5-10 minutes** for deployment to complete

You'll see a screen showing deployment progress. When it says "Your deployment is complete", you're done!

---

## Step 5: Verify It's Working

### 5.1 Check the Agent in Azure

1. In the search bar, type: **Container Apps**
2. You should see `dagster-aca-agent` in the list
3. Click on it
4. **Status should be "Running"**
5. Click **Logs** in the left sidebar
6. Click **Console logs**
7. You should see logs like:
   ```
   Starting Dagster Cloud Agent with ACA Code Server Launcher
   Agent connected to Dagster Cloud
   ```

### 5.2 Check the Agent in Dagster Cloud

1. Go back to https://dagster.cloud
2. Click **Settings** → **Agents**
3. You should see `dagster-aca-agent` with status **Running** (green dot)
4. It might take 1-2 minutes to appear

**If you see the agent listed with a green status, congratulations! 🎉**

---

## Step 6: Deploy Your First Code Location (Optional)

Now that the agent is running, let's deploy a code location to test code servers.

### 6.1 Use Dagster's Example

1. In Dagster Cloud, go to **Deployment** → **Code locations**
2. Click **Add code location**
3. Select **Docker image**
4. Use Dagster's example:
   - **Image**: `dagster/dagster-cloud-examples:latest`
   - **Code location name**: `example-location`
5. Click **Deploy**

### 6.2 Watch the Magic Happen

1. Go back to Azure Portal → **Container Apps**
2. Wait 1-2 minutes
3. You should see a NEW Container App appear:
   - Name: `dagster-prod-example-location`
   - Status: Running
4. This is your code server!

### 6.3 Verify in Dagster Cloud

1. Go to Dagster Cloud → **Deployment**
2. You should see `example-location` with green status
3. Click on it → you'll see example assets and jobs

**You're now running Dagster Cloud on Azure Container Apps!** 🚀

---

## What You've Created

- ✅ **Key Vault** - Securely stores your Dagster credentials
- ✅ **Agent** - Always running on Azure Container Apps (~$20/month)
- ✅ **Code Server** - Created automatically when you deployed code location (~$20/month)
- ✅ **Total cost**: ~$40/month for this demo setup
- ✅ **All in your Azure subscription** - you control everything

---

## Troubleshooting

### Problem: "Key Vault name is not available"
**Solution:** Key Vault names must be globally unique across all of Azure. Add more random numbers to the name (e.g., `dagster-demo-kv-98765`).

### Problem: Deployment validation failed
**Solution:** Check the error message:
- If it mentions Key Vault name: Choose a different unique name
- If it mentions required parameters: Make sure you filled in the agent token value

### Problem: Agent shows "Unhealthy" in Azure
**Solution:**
1. Check logs in Container Apps → Logs → Console logs
2. Common issues:
   - Wrong agent token (verify it matches your Dagster Cloud token)
   - Network connectivity issues (check if Container App can reach dagster.cloud)

### Problem: Agent not showing in Dagster Cloud
**Solution:**
1. Wait 2-3 minutes
2. Check agent token is correct
3. Check Azure logs for errors

### Problem: Code server not launching
**Solution:**
1. Check agent logs in Azure
2. Look for errors mentioning "ACA" or "launcher"
3. Make sure the agent is fully started first

---

## Cleanup (When You're Done Testing)

To delete everything and stop charges:

1. Go to Azure Portal
2. Search for **Resource groups**
3. Click on `dagster-demo-rg`
4. Click **Delete resource group**
5. Type the resource group name to confirm
6. Click **Delete**

This will delete:
- The agent
- Any code servers
- Key Vault
- All associated resources

**Cost stops immediately!**

---

## Next Steps

Once you've verified it works:

1. **Deploy your own code** instead of the example
2. **Set up CI/CD** to auto-deploy on git push
3. **Add more code locations** (each gets its own Container App)
4. **Configure VNet** for private networking
5. **Set up monitoring** with Azure Monitor

---

# 💻 OPTION B: Azure CLI Deployment

For those who prefer command-line automation.

## Step 1: Install Azure CLI

### On macOS:
```bash
brew install azure-cli
```

### On Windows:
Download installer: https://aka.ms/installazurecliwindows

### On Linux:
```bash
curl -sL https://aka.ms/InstallAzureCLIDeb | sudo bash
```

**Verify installation:**
```bash
az --version
# Should show: azure-cli 2.x.x
```

---

## Step 2: Login to Azure

```bash
# Login (opens browser)
az login

# Verify you're logged in
az account show

# If you have multiple subscriptions, set the one you want to use
az account list --output table
az account set --subscription "YOUR_SUBSCRIPTION_NAME_OR_ID"
```

---

## Step 3: Get Dagster Credentials

Same as Option A, Step 1:
1. Go to https://dagster.cloud
2. Settings → Agents → Create Agent Token
3. Save the token, org ID, and deployment name

---

## Step 4: Create Resource Group and Deploy

```bash
# Set variables (REPLACE THESE!)
RESOURCE_GROUP="dagster-demo-rg"
LOCATION="eastus"
KEY_VAULT_NAME="dagster-demo-kv-$RANDOM"  # Adds random number
AGENT_TOKEN="YOUR_AGENT_TOKEN_HERE"
DEPLOYMENT_NAME="prod"
ORG_ID="YOUR_ORG_ID_HERE"

# Create resource group
az group create --name $RESOURCE_GROUP --location $LOCATION

echo "✅ Resource group created: $RESOURCE_GROUP"
```

---

## Step 5: Deploy with ARM Template

```bash
# IMPORTANT: Replace with YOUR custom image URL from Docker setup!
AGENT_IMAGE="ghcr.io/eric-thomas-dagster/dagster-aca-agent:latest"

# Deploy the template (secrets passed as secure parameters)
az deployment group create \
  --resource-group $RESOURCE_GROUP \
  --template-file infra/arm/full-stack-template.json \
  --parameters \
    location=$LOCATION \
    keyVaultName=$KEY_VAULT_NAME \
    agentImage=$AGENT_IMAGE \
    dagsterCloudApiTokenSecretName=DAGSTER-AGENT-TOKEN \
    dagsterCloudApiToken="$AGENT_TOKEN" \
    dagsterDeploymentNameSecretName=DAGSTER-DEPLOYMENT-NAME \
    dagsterDeploymentNameSecretValue="$DEPLOYMENT_NAME" \
    dagsterOrgIdSecretName=DAGSTER-ORG-ID \
    dagsterOrgIdSecretValue="$ORG_ID" \
    agentCpu=0.5 \
    agentMemory=1.0Gi

echo "✅ Deployment complete!"
echo "The template created:"
echo "  - Key Vault with your secrets"
echo "  - Container Apps Environment"
echo "  - Agent Container App (starting up...)"
```

---

## Step 6: Verify

```bash
# Check Container App status
az containerapp list \
  --resource-group $RESOURCE_GROUP \
  --output table

# View agent logs
az containerapp logs show \
  --name dagster-aca-agent \
  --resource-group $RESOURCE_GROUP \
  --follow
```

Press Ctrl+C to stop following logs.

---

## Cleanup

```bash
# Delete everything
az group delete --name $RESOURCE_GROUP --yes --no-wait
```

---

# 🎓 What You Learned

- ✅ How to use Azure Portal for deployments
- ✅ How to create and use Azure Key Vault for secrets
- ✅ How to deploy ARM templates
- ✅ How to work with Azure Container Apps
- ✅ How to connect Dagster Cloud to your Azure infrastructure

---

# 📞 Need Help?

**Common Issues:**
- Azure Portal not loading: Try incognito mode or different browser
- Deployment failed: Check the error message in the deployment logs
- Can't find resources: Make sure you're in the right subscription (check top-right corner)

**Dagster Cloud Support:**
- Documentation: https://docs.dagster.io/dagster-cloud
- Community Slack: https://dagster.io/slack

**Azure Support:**
- Documentation: https://docs.microsoft.com/azure
- Support: Azure Portal → Help + Support

---

# 🚀 You're Ready!

You now have a fully functional Dagster Cloud deployment on Azure Container Apps, all managed through your own Azure subscription.

**What's next?**
- Deploy your own Dagster code
- Set up CI/CD pipelines
- Configure monitoring and alerts
- Scale up for production workloads

Happy orchestrating! 🎉
