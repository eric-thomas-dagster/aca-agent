# Architecture: Fully Serverless Dagster Cloud on Azure

## Overview

This project implements a fully serverless Dagster Cloud deployment on Azure using:
- **Azure Container Apps (ACA)** for the always-on agent
- **Azure Container Instances (ACI)** for on-demand code servers
- **Custom `AciUserCodeLauncher`** to bridge Dagster Cloud with Azure

## Architecture Diagram

```
┌────────────────────────────────────────────────────────────────────────┐
│ Azure Subscription                                                      │
├────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  Resource Group: dagster-aca-rg                                        │
│  ┌──────────────────────────────────────────────────────────────────┐ │
│  │ ┌────────────────────────┐                                       │ │
│  │ │ Container App          │                                       │ │
│  │ │ Name: dagster-agent    │                                       │ │
│  │ │ Image: custom          │                                       │ │
│  │ │ ├─ dagster-cloud-agent │  (base image)                        │ │
│  │ │ ├─ aci_launcher.py     │  (custom code server launcher)       │ │
│  │ │ ├─ dagster.yaml        │  (agent configuration)               │ │
│  │ │ └─ entrypoint.py       │  (Key Vault secrets fetcher)         │ │
│  │ │                        │                                       │ │
│  │ │ Identity:              │                                       │ │
│  │ │ └─ Managed Identity    │ ◄───────────────┐                    │ │
│  │ └────────────────────────┘                  │                    │ │
│  │                                              │                    │ │
│  │ ┌────────────────────────┐                  │                    │ │
│  │ │ Key Vault              │                  │ Permissions        │ │
│  │ │ Name: dagster-kv       │ ◄────────────────┘                    │ │
│  │ │                        │   - Secrets Get/List                  │ │
│  │ │ Secrets:               │                                       │ │
│  │ │ ├─ DAGSTER_API_TOKEN   │                                       │ │
│  │ │ ├─ DEPLOYMENT_NAME     │                                       │ │
│  │ │ └─ ORG_ID              │                                       │ │
│  │ └────────────────────────┘                                       │ │
│  │                                                                   │ │
│  │ ┌────────────────────────┐                                       │ │
│  │ │ VNet + Subnet          │                                       │ │
│  │ │ ├─ ACA integrated      │                                       │ │
│  │ │ └─ ACI integrated      │                                       │ │
│  │ └────────────────────────┘                                       │ │
│  └──────────────────────────────────────────────────────────────────┘ │
│                                                                         │
│  Resource Group: dagster-aca-rg-code-servers                           │
│  ┌──────────────────────────────────────────────────────────────────┐ │
│  │ Container Instances (Created Dynamically)                        │ │
│  │                                                                   │ │
│  │ ┌────────────────────────┐   ┌────────────────────────┐         │ │
│  │ │ ACI: code-server-1     │   │ ACI: code-server-2     │         │ │
│  │ │ Image: user-code:v1    │   │ Image: user-code:v2    │   ...  │ │
│  │ │ State: Running         │   │ State: Terminated      │         │ │
│  │ │ CPU: 0.5, RAM: 2GB     │   │ CPU: 1.0, RAM: 4GB     │         │ │
│  │ └────────────────────────┘   └────────────────────────┘         │ │
│  │                                                                   │ │
│  │ Lifecycle:                                                        │ │
│  │ 1. Agent creates container when code location deployed           │ │
│  │ 2. Container runs jobs                                           │ │
│  │ 3. Auto-terminates after TTL (default: 5 minutes idle)           │ │
│  └──────────────────────────────────────────────────────────────────┘ │
│                                                                         │
└────────────────────────────────────────────────────────────────────────┘
                                 │
                                 │ gRPC over HTTPS
                                 │
                                 ▼
                    ┌────────────────────────┐
                    │  Dagster Cloud         │
                    │  (Control Plane)       │
                    │                        │
                    │  - Agent registration  │
                    │  - Job orchestration   │
                    │  - Metadata storage    │
                    │  - UI/API              │
                    └────────────────────────┘
```

## Components

### 1. Dagster Cloud Agent (ACA)

**Runtime:** Azure Container Apps
**Base Image:** `dagster/dagster-cloud-agent:latest`
**Always Running:** Yes (minReplicas: 1)

**Responsibilities:**
- Maintain persistent gRPC connection to Dagster Cloud
- Receive code location deployment notifications
- Launch ACI containers for code servers using `AciUserCodeLauncher`
- Monitor code server health
- Clean up terminated containers

**Key Files:**
- `app/entrypoint.py` - Fetches secrets from Key Vault, launches agent
- `app/aci_launcher.py` - Custom code server launcher for ACI
- `app/dagster.yaml` - Agent configuration

**Environment Variables:**
- `DAGSTER_CLOUD_API_TOKEN` - Agent authentication (from Key Vault)
- `DAGSTER_CLOUD_DEPLOYMENT_NAME` - Deployment identifier
- `DAGSTER_CLOUD_ORG_ID` - Organization identifier
- `AZURE_SUBSCRIPTION_ID` - For ACI operations
- `CODE_SERVER_RESOURCE_GROUP` - Where to create code servers
- `CODE_SERVER_SUBNET_ID` - VNet integration (optional)

### 2. ACI User Code Launcher

**File:** `app/aci_launcher.py`
**Class:** `AciUserCodeLauncher`

**How It Works:**

```python
# Configuration from dagster.yaml
user_code_launcher:
  module: aci_launcher
  class: AciUserCodeLauncher
  config:
    subscription_id: {AZURE_SUBSCRIPTION_ID}
    resource_group: dagster-aca-rg-code-servers
    location: eastus
    subnet_id: {optional}
    cpu: 0.5
    memory: 2.0
```

**Lifecycle:**

1. **Deployment Event** - Dagster Cloud notifies agent of new code location
2. **Launch** - `launch_code_server()` creates ACI container group:
   ```python
   container_group = {
       "location": "eastus",
       "containers": [{
           "name": "dagster-code-server",
           "image": "myacr.azurecr.io/dagster-code:v1",
           "resources": {"requests": {"cpu": 0.5, "memoryInGB": 2}},
           "environment_variables": [
               {"name": "DAGSTER_CLOUD_DEPLOYMENT_NAME", "value": "prod"},
               {"name": "DAGSTER_CLOUD_URL", "value": "https://dagster.cloud"},
               ...
           ]
       }],
       "os_type": "Linux",
       "restart_policy": "Never",
       "subnet_ids": [{"id": subnet_id}] if subnet_id else None
   }
   ```
3. **Registration** - Code server starts, registers with Dagster Cloud
4. **Job Execution** - Code server executes runs
5. **Termination** - After `server_ttl` idle time, container terminates
6. **Cleanup** - Agent deletes container group

**API Calls:**
- `azure.mgmt.containerinstance.ContainerInstanceManagementClient`
  - `container_groups.begin_create_or_update()` - Launch
  - `container_groups.get()` - Status
  - `container_groups.begin_delete()` - Cleanup

### 3. Code Servers (ACI)

**Runtime:** Azure Container Instances
**Image:** User-provided (built from Dagster project)
**Lifecycle:** On-demand (created/destroyed per deployment)

**Responsibilities:**
- Register as code location with Dagster Cloud
- Serve Dagster definitions (assets, jobs, schedules, sensors)
- Execute runs when triggered
- Report status/logs to Dagster Cloud

**Networking:**
- Can integrate with VNet via `subnet_id`
- Private IP only (no public exposure)
- Communicates with Dagster Cloud via HTTPS/gRPC

**Resource Limits:**
- Default: 0.5 vCPU, 2GB RAM
- Customizable per code location via `container_context`
- Azure limits: Up to 4 vCPU, 16GB RAM per container

### 4. Infrastructure (ARM/Bicep)

**Template:** `infra/bicep/full-stack.bicep`

**Creates:**
1. VNet + Subnet (for ACA and ACI)
2. Log Analytics Workspace
3. Container Apps Environment
4. User-Assigned Managed Identity
5. Key Vault with access policy
6. Container App (agent)
7. Network Security Group
8. Optional NAT Gateway

**Outputs:**
- `identityPrincipalId` - For role assignments
- `codeServerResourceGroupName` - Where code servers will be created
- `requiredRoleDefinitionIds` - Roles to assign

**Post-Deployment:**
Run `infra/setup-code-servers.sh` to:
1. Create code servers resource group
2. Assign Contributor role to managed identity
3. Optionally assign AcrPull role

## Security Model

### Authentication Flow

```
┌─────────────┐
│ Agent (ACA) │
└──────┬──────┘
       │ 1. Managed Identity
       │    (DefaultAzureCredential)
       ▼
┌──────────────┐
│  Key Vault   │  2. Fetch secrets:
│              │     - DAGSTER_CLOUD_API_TOKEN
│              │     - DEPLOYMENT_NAME
└──────┬───────┘     - ORG_ID
       │
       │ 3. Use API token
       ▼
┌──────────────┐
│ Dagster Cloud│  4. Authenticate agent
└──────┬───────┘     Establish gRPC connection
       │
       │ 5. Deploy code location
       ▼
┌──────────────┐
│  Agent       │  6. Use Managed Identity
│              │     to call Azure API
└──────┬───────┘
       │
       │ 7. Create ACI container
       ▼
┌──────────────┐
│ Code Server  │  8. Use same managed
│  (ACI)       │     identity (inherited)
└──────┬───────┘
       │ 9. Register with Dagster Cloud
       ▼
┌──────────────┐
│ Dagster Cloud│  10. Execute runs
└──────────────┘
```

### Permissions Required

**Managed Identity Roles:**

1. **Key Vault Secrets Officer** (on Key Vault)
   - Scope: `/subscriptions/{sub}/resourceGroups/{rg}/providers/Microsoft.KeyVault/vaults/{kv}`
   - Permissions: `get`, `list` secrets
   - Purpose: Agent fetches Dagster API token

2. **Contributor** (on code servers resource group)
   - Scope: `/subscriptions/{sub}/resourceGroups/{rg}-code-servers`
   - Purpose: Create/delete ACI containers

3. **AcrPull** (on ACR) - Optional
   - Scope: `/subscriptions/{sub}/resourceGroups/{acr-rg}/providers/Microsoft.ContainerRegistry/registries/{acr}`
   - Purpose: Pull private container images

### Network Security

**Default (No VNet):**
- Agent: Public IP (HTTPS only)
- Code Servers: Public IP (HTTPS only)
- All traffic encrypted via TLS

**VNet Integration:**
- Agent: Private IP in ACA subnet
- Code Servers: Private IP in ACI subnet
- No public exposure
- Can access private Azure resources (Storage, SQL, etc.)

**NSG Rules:**
- Allow outbound HTTPS (443) to Dagster Cloud
- Allow outbound HTTPS (443) to Azure APIs
- Optional: Allow outbound to customer data sources

## Cost Model

### Azure Container Apps (Agent)

**Pricing:** Pay for allocated resources
**Formula:** `(vCPU × $0.000024/sec) + (Memory GB × $0.000003/sec)`

**Example (Default):**
- vCPU: 0.25
- Memory: 1GB
- Always running (730 hours/month)
- Cost: ~$20/month

### Azure Container Instances (Code Servers)

**Pricing:** Pay per second running
**Formula:** `(vCPU × $0.0000125/sec) + (Memory GB × $0.0000014/sec)`

**Example (Default):**
- vCPU: 0.5
- Memory: 2GB
- Running 100 hours/month (10 jobs × 10 hours each)
- Cost: ~$5/month

**Total: ~$25/month for typical workload**

### Cost Optimization

1. **Tune `server_ttl`:**
   - Lower TTL = faster termination = lower cost
   - Higher TTL = keep warm = faster job starts
   - Recommended: 300 seconds (5 minutes)

2. **Right-size code servers:**
   - Start with 0.5 vCPU, 2GB RAM
   - Monitor and adjust per code location
   - Use `container_context` for custom sizing

3. **Use spot instances:** (Future)
   - ACI doesn't support spot, but could use ACA Jobs

4. **Batch jobs:**
   - Group multiple runs to reuse code server
   - Reduces container churn

## Monitoring & Observability

### Agent Logs

```bash
# Real-time logs
az containerapp logs show -n dagster-aca-agent -g dagster-rg --follow

# Query specific time range
az monitor log-analytics query \
  --workspace {workspace-id} \
  --analytics-query "ContainerAppConsoleLogs_CL | where ContainerName_s == 'dagster-agent'"
```

### Code Server Logs

```bash
# List running code servers
az container list -g dagster-rg-code-servers -o table

# View specific code server logs
az container logs -g dagster-rg-code-servers -n dagster-prod-project-123456

# Follow logs
az container logs -g dagster-rg-code-servers -n dagster-prod-project-123456 --follow
```

### Key Metrics

**Agent Health:**
- Container restart count
- CPU/memory usage
- gRPC connection status

**Code Servers:**
- Launch time (target: <30 seconds)
- Active containers
- Terminated containers (cleanup)
- Failed launches

**Costs:**
- ACA consumption (always-on)
- ACI consumption (per-second)
- Total monthly spend

### Alerts

**Recommended Azure Monitor Alerts:**
1. Agent restart > 3 times/hour
2. Code server launch failures > 5/hour
3. Code server launch time > 60 seconds
4. Daily cost > threshold

## Troubleshooting

### Agent Won't Start

```bash
# Check agent logs
az containerapp logs show -n dagster-agent -g dagster-rg --tail 100

# Common issues:
# - Missing DAGSTER_CLOUD_API_TOKEN
# - Invalid API token
# - Key Vault access denied
# - AZURE_SUBSCRIPTION_ID not set
```

### Code Servers Not Launching

```bash
# Check agent logs for ACI errors
az containerapp logs show -n dagster-agent -g dagster-rg --follow | grep "ACI"

# Common issues:
# - Managed identity lacks Contributor role on code-servers RG
# - Invalid subscription ID
# - Subnet too small (need /24 or larger)
# - ACR access denied
```

### Code Server Launch Slow

```bash
# Check ACI provisioning state
az container show -g dagster-rg-code-servers -n {container-name} --query "provisioningState"

# Common issues:
# - Large image size (optimize: use multi-stage builds, minimize layers)
# - Cold start (first pull from ACR)
# - Subnet IP exhaustion
```

### High Costs

```bash
# Check running code servers
az container list -g dagster-rg-code-servers --query "[].{Name:name, State:containers[0].instanceView.currentState.state}" -o table

# Common issues:
# - Code servers not terminating (check server_ttl)
# - Too many concurrent code servers
# - Oversized containers (right-size CPU/memory)
```

## Limitations & Known Issues

1. **No Built-in Autoscaling for Agent**
   - Agent runs fixed replicas (minReplicas = maxReplicas)
   - For high load, manually increase replicas

2. **ACI Quotas**
   - Default: 100 container groups per region per subscription
   - Can be increased via support ticket

3. **Subnet Size**
   - ACI requires /24 or larger subnet
   - Plan for growth

4. **No Spot/Low-Priority**
   - ACI doesn't support spot instances
   - Always pay full price for code servers

5. **Cold Start Latency**
   - First code server launch: 30-60 seconds
   - Subsequent launches: 10-30 seconds
   - Mitigate: Increase `server_ttl` to keep warm

6. **Custom Implementation**
   - `AciUserCodeLauncher` is custom (not official Dagster)
   - You maintain compatibility with Dagster Cloud API changes
   - Test thoroughly before production

## Future Enhancements

1. **Azure Container Apps Jobs** for runs
   - More cost-effective for short-lived runs
   - Better isolation per run

2. **KEDA Autoscaling** for agent
   - Scale agent replicas based on queue depth

3. **Distributed Tracing**
   - Azure Application Insights integration
   - End-to-end observability

4. **Multi-Region**
   - Deploy agents in multiple regions
   - Route code locations to nearest agent

5. **Prometheus Metrics**
   - Export custom metrics for Grafana dashboards

## References

- [Dagster Cloud Documentation](https://docs.dagster.io/dagster-plus)
- [Azure Container Apps](https://learn.microsoft.com/azure/container-apps/)
- [Azure Container Instances](https://learn.microsoft.com/azure/container-instances/)
- [Azure SDK for Python - Container Instances](https://learn.microsoft.com/python/api/azure-mgmt-containerinstance/)
