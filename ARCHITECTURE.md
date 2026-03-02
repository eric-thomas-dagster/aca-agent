# Architecture: Dagster Cloud Agent on Azure Container Apps

## Overview

This project runs a fully serverless Dagster Cloud hybrid deployment on Azure using
**Azure Container Apps (ACA)** for every component — agent, code servers, and run workers.
Everything lives in a single ACA environment within a single resource group.

```
┌────────────────────────────────────────────────────────────────────────┐
│ Azure Subscription                                                      │
├────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  Resource Group: dagster-aca-rg                                        │
│  ┌──────────────────────────────────────────────────────────────────┐ │
│  │                                                                   │ │
│  │  Container Apps Environment (dagster-aca-env)                    │ │
│  │  ┌─────────────────────────────────────────────────────────┐    │ │
│  │  │                                                          │    │ │
│  │  │  ┌──────────────────────┐  ┌───────────────────────┐   │    │ │
│  │  │  │ Agent (2 replicas)   │  │ Code Server: proj-A    │   │    │ │
│  │  │  │ dagster-aca-agent    │  │ dagster-prod-proj-a    │   │    │ │
│  │  │  │                      │  │ min/max: 1             │   │    │ │
│  │  │  │ AcaUserCodeLauncher  │  └───────────────────────┘   │    │ │
│  │  │  │ AcaRunLauncher       │  ┌───────────────────────┐   │    │ │
│  │  │  │ (always-on)          │  │ Code Server: proj-B    │   │    │ │
│  │  │  └──────────────────────┘  │ dagster-prod-proj-b    │   │    │ │
│  │  │                            └───────────────────────┘   │    │ │
│  │  │  ┌───────────────────────────────────────────────────┐ │    │ │
│  │  │  │ Run Workers (ephemeral, scale to 0 after run)      │ │    │ │
│  │  │  │  dagster-run-<id>-0  dagster-run-<id>-1  ...       │ │    │ │
│  │  │  │  Cleaned up by background thread after completion  │ │    │ │
│  │  │  └───────────────────────────────────────────────────┘ │    │ │
│  │  └─────────────────────────────────────────────────────────┘    │ │
│  │                                                                   │ │
│  │  ┌──────────────────────────┐  ┌──────────────────────────────┐ │ │
│  │  │ Key Vault (dagster-kv)   │  │ Log Analytics Workspace      │ │ │
│  │  │ - DAGSTER_CLOUD_API_TOKEN│  │ - Container App console logs │ │ │
│  │  │ - DAGSTER_ORG_ID         │  │ - Key Vault audit logs       │ │ │
│  │  │ - DAGSTER_DEPLOYMENT_NAME│  │ - Configurable retention     │ │ │
│  │  │ Audit logs → Log Analytics  └──────────────────────────────┘ │ │
│  │  │ Optional: private endpoint│                                   │ │
│  │  └──────────────────────────┘                                   │ │
│  │                                                                   │ │
│  │  ┌──────────────────────────┐  ┌──────────────────────────────┐ │ │
│  │  │ Managed Identity         │  │ VNet + NSG                   │ │ │
│  │  │ - KV Get/List secrets    │  │ - Subnet delegated to ACA    │ │ │
│  │  │ - Container Apps CRUD    │  │ - Service-tag egress rules   │ │ │
│  │  │ CanNotDelete lock        │  │ - DenyAll catch-all          │ │ │
│  │  └──────────────────────────┘  └──────────────────────────────┘ │ │
│  └──────────────────────────────────────────────────────────────────┘ │
└────────────────────────────────────────────────────────────────────────┘
                                 │
                                 │ gRPC / HTTPS
                                 ▼
                    ┌────────────────────────────┐
                    │  Dagster+ Control Plane     │
                    │  dagster.cloud (US)         │
                    │  eu.dagster.cloud (EU)      │
                    └────────────────────────────┘
```

---

## Components

### 1. Dagster Cloud Agent (ACA)

**Runtime:** Azure Container Apps
**Base Image:** `dagster/dagster-cloud-agent:1.12.6`
**Always Running:** Yes (default 2 replicas for HA)

**Responsibilities:**
- Maintain persistent gRPC connection to Dagster+
- Receive code location deployment notifications from Dagster+
- Create/update/delete code server Container Apps via `AcaUserCodeLauncher`
- Create ephemeral run worker Container Apps via `AcaRunLauncher`
- Run a background cleanup thread that deletes completed run workers

**Key Files:**
- `app/entrypoint.py` — Fetches secrets from Key Vault, expands `dagster.yaml`, starts agent
- `app/aca_launcher.py` — `AcaUserCodeLauncher` and `AcaRunLauncher` implementations
- `app/dagster.yaml` — Agent configuration (env-var templated)

**Environment Variables (set by ARM/Bicep template):**

| Variable | Description |
|---|---|
| `DAGSTER_CLOUD_API_TOKEN` | Agent token (fetched from Key Vault by entrypoint) |
| `DAGSTER_CLOUD_DEPLOYMENT_NAME` | Dagster+ deployment name |
| `DAGSTER_CLOUD_ORG_ID` | Dagster+ organization ID |
| `DAGSTER_CLOUD_BASE_DOMAIN` | `dagster.cloud` or `eu.dagster.cloud` |
| `AZURE_SUBSCRIPTION_ID` | Azure subscription |
| `AGENT_RESOURCE_GROUP` | Resource group where Container Apps are created |
| `ENVIRONMENT_NAME` | ACA environment name |
| `AZURE_LOCATION` | Azure region |
| `AZURE_CLIENT_ID` | Managed identity client ID |
| `CODE_SERVER_IDENTITY_ID` | Managed identity resource ID (assigned to code servers) |
| `CODE_SERVER_CPU` | Default vCPU for code servers (e.g. `0.5`) |
| `CODE_SERVER_MEMORY` | Default memory for code servers (e.g. `1.0Gi`) |

---

### 2. AcaUserCodeLauncher

**File:** `app/aca_launcher.py`
**Class:** `AcaUserCodeLauncher`

Manages long-lived code server Container Apps — one per code location. When Dagster+
notifies the agent of a new or updated code location, the launcher creates or updates the
corresponding Container App in the same ACA environment.

**Container App naming:** `dagster-{deployment}-{location}` (max 32 chars).
Names that would exceed 32 chars get a deterministic 7-character SHA-256 suffix to prevent
silent collisions: `{raw[:24]}-{hash[:7]}`.

**Compute sizing:** Defaults from `CODE_SERVER_CPU` / `CODE_SERVER_MEMORY` env vars
(set via template parameters `codeServerCpu` / `codeServerMemory`). Can be overridden
per code location via `container_context` in the Dagster+ code location configuration.

---

### 3. AcaRunLauncher

**File:** `app/aca_launcher.py`
**Class:** `AcaRunLauncher`

Creates ephemeral run worker Container Apps for each job execution. Run workers scale
to 0 after the run completes — the container process exits but the Container App object
persists and counts against the 200-app-per-environment limit.

**Cleanup thread:** A background daemon thread (interval configurable via
`RUN_APP_CLEANUP_INTERVAL_SECS`, default 300s) scans for run worker Container Apps
with `running_status != "Running"` that are at least `RUN_APP_CLEANUP_MIN_AGE_SECS`
old (default 120s) and deletes them.

**Run worker Container App tags:**
- `dagster-component: run-worker` (used by cleanup thread to identify run apps)

---

### 4. Infrastructure (ARM / Bicep)

**Templates:**
- `infra/bicep/full-stack.bicep` — Bicep source
- `infra/arm/full-stack-template.json` — ARM JSON equivalent

**Resources deployed:**

| Resource | Notes |
|---|---|
| VNet + Subnet | Delegated to `Microsoft.App/environments` |
| NSG | Service-tag egress rules; DenyAll catch-all |
| Log Analytics Workspace | Configurable retention (30–730 days) |
| Container Apps Environment | Integrated with VNet |
| User-Assigned Managed Identity | `CanNotDelete` lock by default |
| Key Vault | `CanNotDelete` lock; optional private endpoint; audit logs → Log Analytics |
| Container App (agent) | 2 replicas default; zero-downtime deploys on by default |
| Role Assignment | Custom minimal role or Contributor fallback |
| Optional: Azure Monitor alerts | Agent restarts, agent not running, KV failures |

**Pre-deployment step (recommended):** Deploy `infra/arm/aca-agent-role.json`
(or `infra/bicep/aca-agent-role.bicep`) at subscription scope to create the minimal
custom RBAC role. Pass its output `roleDefinitionId` as `agentRoleDefinitionId` to
the main template.

```bash
# 1. Deploy the custom role (once per subscription)
az deployment sub create \
  --location eastus \
  --template-file infra/bicep/aca-agent-role.bicep \
  --query properties.outputs.roleDefinitionId.value -o tsv
# → /subscriptions/{sub}/providers/Microsoft.Authorization/roleDefinitions/{guid}

# 2. Deploy the full stack, passing the role definition ID
az deployment group create \
  --resource-group my-rg \
  --template-file infra/bicep/full-stack.bicep \
  --parameters agentRoleDefinitionId=<output-from-above> ...
```

---

## Security Model

### Authentication Flow

```
Agent (ACA)
  │
  │ 1. DefaultAzureCredential (Managed Identity)
  ▼
Key Vault
  │ 2. Get secrets: API token, deployment name, org ID
  ▼
Agent starts, connects to Dagster+
  │ 3. Agent token → gRPC connection
  ▼
Dagster+ Control Plane
  │ 4. Deploy code location notification
  ▼
Agent (AcaUserCodeLauncher)
  │ 5. Managed Identity → Azure Container Apps API
  ▼
Code Server Container App (created in same ACA environment)
  │ 6. Agent Managed Identity assigned to code server
  ▼
Dagster+ Control Plane (code server registers and executes runs)
```

### RBAC (Managed Identity Permissions)

**Recommended — custom minimal role** (deploy `infra/arm/aca-agent-role.json` first):

| Permission | Purpose |
|---|---|
| `Microsoft.App/containerApps/read` | List/get code servers and run workers |
| `Microsoft.App/containerApps/write` | Create/update code servers and run workers |
| `Microsoft.App/containerApps/delete` | Delete completed run workers |
| `Microsoft.App/containerApps/revisions/read` | Read revision status |
| `Microsoft.App/managedEnvironments/read` | Look up environment ID |
| `Microsoft.App/managedEnvironments/join/action` | Join the ACA environment |
| `Microsoft.ManagedIdentity/userAssignedIdentities/assign/action` | Assign identity to code servers |

**Fallback:** Built-in `Contributor` role on the resource group (functional but broader than necessary).

**Key Vault access policy:** `Get` + `List` secrets (scoped to the agent's managed identity only).

### Network Security

**NSG egress rules (in priority order):**

| Rule | Destination | Port | Purpose |
|---|---|---|---|
| AllowAzureActiveDirectory | `AzureActiveDirectory` | 443 | Managed Identity token |
| AllowAzureKeyVault | `AzureKeyVault` | 443 | Secret fetching |
| AllowAzureContainerRegistry | `AzureContainerRegistry` | 443 | Image pulls |
| AllowAzureMonitor | `AzureMonitor` | 443 | Log ingestion |
| AllowAzureCloud | `AzureCloud` | 443 | ACA control plane |
| AllowHttpsInternet | `Internet` | 443 | Dagster+ endpoints |
| DenyAllOutbound | `*` | `*` | Catch-all deny |

For FQDN-level restriction (e.g. allow only `dagster.cloud` not all of Internet),
replace the Internet rule with an Azure Firewall policy.

**Optional Key Vault private endpoint:** When `enableKeyVaultPrivateEndpoint=true`,
a private endpoint + private DNS zone is created and Key Vault public access is disabled.
Requires VNet integration (included by default).

### Compliance Features

| Feature | Default | Parameter |
|---|---|---|
| Key Vault audit logs → Log Analytics | Always on | — |
| CanNotDelete lock on Key Vault | On | `enableResourceLocks` |
| CanNotDelete lock on Managed Identity | On | `enableResourceLocks` |
| Log retention | 90 days | `logRetentionDays` (30–730) |
| Azure Monitor alerts | Off | `enableAlerts` + `alertEmailAddress` |
| Key Vault private endpoint | Off | `enableKeyVaultPrivateEndpoint` |

---

## Cost Model

All components run on ACA, billed by allocated vCPU-seconds and memory-second.

**Formula:** `(vCPU × $0.000024/sec) + (Memory GiB × $0.000003/sec)`

| Component | vCPU | Memory | Hours/month | Est. cost |
|---|---|---|---|---|
| Agent (2 replicas) | 0.25 each | 1 GiB each | 730 (always-on) | ~$40/month |
| Code Server (per location) | 0.5 | 1 GiB | 730 (always-on) | ~$20/month |
| Run Workers | 0.5 | 1 GiB | Per-run only | ~$0 when idle |

**Example: 1 agent + 3 code locations:** ~$100/month

**vs. AKS minimum (~$170/month):** ~40% savings with no cluster management overhead.

**Cost optimization tips:**
- Right-size code servers using `codeServerCpu` / `codeServerMemory` template params
- Override per code location via `container_context` in Dagster+ code location config
- Run workers scale to 0 automatically — no cost between runs
- Cleanup thread ensures completed run worker objects don't accumulate

---

## Multi-Region Support

| Region | `dagsterRegion` | Base domain |
|---|---|---|
| US | `us` (default) | `dagster.cloud` |
| EU | `eu` | `eu.dagster.cloud` |
| Custom/future | — | Set `dagsterBaseDomainOverride` |

The base domain flows to the `DAGSTER_CLOUD_BASE_DOMAIN` env var, which is used by
`dagster.yaml` to construct the agent URL: `https://{org}.agent.{base_domain}`.

---

## Monitoring & Observability

### Logs

```bash
# Agent logs (real-time)
az containerapp logs show -n dagster-aca-agent -g my-rg --follow

# Query via Log Analytics
az monitor log-analytics query \
  --workspace <workspace-id> \
  --analytics-query "ContainerAppConsoleLogs_CL | where ContainerName_s == 'dagster-agent' | order by TimeGenerated desc"

# Key Vault audit log query
az monitor log-analytics query \
  --workspace <workspace-id> \
  --analytics-query "AzureDiagnostics | where ResourceType == 'VAULTS' | where ResultType != 'Success'"
```

### Azure Monitor Alerts (optional, `enableAlerts=true`)

| Alert | Severity | Condition |
|---|---|---|
| Agent restarts | 2 | `RestartCount > 0` in 5m window |
| Agent not running | 1 | `RunningReplicaCount < 1` over 15m |
| Key Vault failures | 2 | `ServiceApiResult` with 4xx/5xx > 0 over 15m |

All alerts route to an email action group (`alertEmailAddress`).

### Key Metrics to Monitor

| Metric | Target |
|---|---|
| Agent replica count | ≥ 2 (HA) |
| Agent restart count | 0 |
| Code server replica count | 1 per location |
| KV API success rate | 100% |
| Run worker count | Should trend to 0 between runs |

---

## Limitations & Known Issues

1. **200 Container App limit per environment**
   The ACA environment supports up to 200 Container Apps. Code servers + run workers
   both count. The background cleanup thread handles run workers automatically. If you
   have many code locations (close to 200), contact Azure support to request a quota
   increase.

2. **Agent replicas are fixed, not autoscaled**
   `minReplicas == maxReplicas`. Scale by setting `numReplicas` (1–5). KEDA-based
   autoscaling based on job queue depth is a potential future enhancement.

3. **No spot/preemptible support**
   ACA doesn't support spot pricing for always-on Container Apps. Run workers
   (scale-to-zero) incur no cost when idle.

4. **Cold start latency for code servers**
   First startup: 30–60 seconds (image pull + process start). Subsequent starts
   are faster if the image is already cached in the environment. Code servers are
   always-on so this only affects initial deployment or restarts.

5. **Single ACA environment per deployment**
   All code servers and run workers share one ACA environment. Workload isolation
   between environments requires separate deployments.

---

## Future Enhancements

1. **KEDA autoscaling for agent** — scale replicas based on pending job queue depth
2. **Application Insights integration** — distributed tracing across agent and code servers
3. **Multi-region deployment** — active-active agents across Azure regions
4. **Azure Container Apps Jobs** — for truly ephemeral run workers with better isolation
5. **Prometheus metrics export** — custom metrics for Grafana dashboards

---

## References

- [Dagster+ Documentation](https://docs.dagster.io/dagster-plus)
- [Azure Container Apps](https://learn.microsoft.com/azure/container-apps/)
- [Azure Container Apps Quotas](https://learn.microsoft.com/azure/container-apps/quotas)
- [Azure Key Vault](https://learn.microsoft.com/azure/key-vault/)
- [Azure Monitor Metric Alerts](https://learn.microsoft.com/azure/azure-monitor/alerts/alerts-metric)
