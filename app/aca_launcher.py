#!/usr/bin/env python3
"""
ACA User Code Launcher for Dagster Cloud

This custom launcher enables Dagster Cloud agents to launch code servers
as Azure Container Apps, providing a fully managed container platform on Azure.

Architecture:
- Agent runs on Azure Container Apps (always-on)
- Code servers launch as Container Apps in the same environment (long-lived)
- All within customer's Azure subscription

Author: Dagster Solutions Engineering
License: MIT
"""

import os
import logging
import time
import asyncio
from typing import Dict, Optional, List, Collection, NamedTuple
from dagster_cloud.workspace.user_code_launcher import DagsterCloudUserCodeLauncher
from dagster_cloud.workspace.user_code_launcher.user_code_launcher import (
    DagsterCloudGrpcServer,
    ServerEndpoint,
    UserCodeLauncherEntry,
)
from dagster_cloud.api.dagster_cloud_api import UserCodeDeploymentType
from dagster_cloud.execution.monitoring import CloudContainerResourceLimits
from dagster._core.launcher import RunLauncher
from azure.identity import DefaultAzureCredential
from azure.mgmt.appcontainers import ContainerAppsAPIClient
from azure.mgmt.appcontainers.models import (
    ContainerApp,
    Container,
    Configuration,
    Template,
    Scale,
    ScaleRule,
    Ingress,
    Secret,
    EnvironmentVar,
    ContainerResources,
    ContainerAppProbe,
    ContainerAppProbeHttpGet,
    RegistryCredentials,
    ManagedServiceIdentity,
    UserAssignedIdentity,
)

logger = logging.getLogger(__name__)


class AcaRunLauncher(RunLauncher):
    """
    Run launcher for Azure Container Apps.

    This launcher creates temporary Container App instances for individual run executions.
    Each run gets its own isolated container that scales down to 0 after completion.
    """

    def __init__(self, inst_data=None, **kwargs):
        """Initialize the ACA run launcher with Azure credentials."""
        super().__init__()

        # Get Azure configuration from environment (set by agent)
        self.subscription_id = os.getenv("AZURE_SUBSCRIPTION_ID")
        self.resource_group = os.getenv("AGENT_RESOURCE_GROUP", "dagster-aca-rg")
        self.environment_name = os.getenv("ENVIRONMENT_NAME", "dagster-aca-env")
        self.location = os.getenv("AZURE_LOCATION", "eastus")
        self.code_server_identity_id = os.getenv("CODE_SERVER_IDENTITY_ID")

        # Required tags for Azure policy
        self.required_tags = {"Department": os.getenv("AZURE_TAG_DEPARTMENT", "Engineering")}

        # Initialize Azure client
        credential = DefaultAzureCredential()
        self.aca_client = ContainerAppsAPIClient(credential, self.subscription_id)

        # Get environment resource ID
        env = self.aca_client.managed_environments.get(
            resource_group_name=self.resource_group,
            environment_name=self.environment_name
        )
        self.environment_id = env.id

        logger.info(f"AcaRunLauncher initialized: rg={self.resource_group}, env={self.environment_name}")

    @property
    def supports_check_run_worker_health(self) -> bool:
        """Whether this launcher supports checking run worker health."""
        return False

    def launch_run(self, context):
        """
        Launch a Dagster run in a new Container App instance.

        Creates a temporary Container App that:
        - Executes the run using `dagster api execute_run`
        - Scales down to 0 after completion
        - Has no ingress (no external access needed)
        """
        from dagster_cloud.instance import DagsterCloudAgentInstance
        from dagster._grpc.types import ExecuteRunArgs
        from dagster import check

        run = context.dagster_run
        run_id = run.run_id

        logger.info(f"Launching run {run_id} on Azure Container Apps")

        # Get the job origin for building the execute_run command
        # Following OSS ECS launcher pattern: use context.job_code_origin
        job_origin = check.not_none(
            context.job_code_origin,
            "job_code_origin must be set on the context in order to launch runs"
        )

        # Get deployment and location names from run
        # Follow the ECS launcher pattern: use remote_job_origin
        # This is the canonical way to get location info in Dagster Cloud

        # Get deployment name from instance (preferred) or tags as fallback
        if hasattr(self, '_instance') and hasattr(self._instance, 'deployment_name'):
            deployment_name = self._instance.deployment_name
        else:
            deployment_name = (
                run.tags.get("dagster/deployment") or
                run.tags.get("dagster-cloud/deployment") or
                "prod"  # Default fallback
            )

        # Get location name from remote_job_origin (same pattern as ECS launcher)
        location_name = None
        if hasattr(run, 'remote_job_origin') and run.remote_job_origin:
            try:
                location_name = run.remote_job_origin.repository_origin.code_location_origin.location_name
                logger.info(f"Got location name from remote_job_origin: {location_name}")
            except (AttributeError, TypeError) as e:
                logger.warning(f"Could not get location from remote_job_origin: {e}")

        # Fallback: try tags (less common but may exist in some setups)
        if not location_name:
            location_name = (
                run.tags.get("dagster/code_location") or
                run.tags.get("dagster-cloud/code-location")
            )
            if location_name:
                logger.info(f"Got location name from tags: {location_name}")

        if not location_name:
            # Log available info for debugging
            logger.error(f"Run {run_id} tags: {run.tags}")
            logger.error(f"Run {run_id} has remote_job_origin: {hasattr(run, 'remote_job_origin')}")
            raise ValueError(
                f"Could not determine code location for run {run_id}. "
                f"Available tags: {list(run.tags.keys())}"
            )

        logger.info(f"Run {run_id} is for location {deployment_name}:{location_name}")

        # Get the container image from the running code server
        # The code server should already be deployed for this location
        code_server_name = f"dagster-{deployment_name}-{location_name}"[:32].lower().replace("_", "-")

        try:
            code_server_app = self.aca_client.container_apps.get(
                resource_group_name=self.resource_group,
                container_app_name=code_server_name
            )
            # Get image from the code server's container spec
            container_image = code_server_app.template.containers[0].image
            logger.info(f"Using image from code server {code_server_name}: {container_image}")
        except Exception as e:
            raise ValueError(
                f"Could not find code server {code_server_name} to get image for run {run_id}. "
                f"Ensure the code location is deployed before launching runs. Error: {e}"
            )

        # Generate Container App name for this run
        app_name = f"dagster-run-{run_id[:8]}"
        app_name = app_name.lower().replace("_", "-")

        logger.info(f"Creating Container App for run: app={app_name}, image={container_image}")

        # Build environment variables for the run
        # Start with run-specific vars
        job_name = run.remote_job_origin.job_name if run.remote_job_origin else "unknown"
        env_vars = [
            EnvironmentVar(name="DAGSTER_RUN_JOB_NAME", value=job_name),
            EnvironmentVar(name="DAGSTER_RUN_ID", value=run_id),
        ]

        # Copy environment variables from the code server
        # The run needs the same env vars as the code server (API keys, storage config, etc.)
        if code_server_app.template.containers[0].env:
            for env_var in code_server_app.template.containers[0].env:
                # Don't copy DAGSTER_CLOUD_CODE_LOCATION_NAME as it's not needed for runs
                if env_var.name not in ["DAGSTER_CLOUD_CODE_LOCATION_NAME"]:
                    env_vars.append(env_var)

        # Build the command for executing the run
        # Following the OSS ECS/Docker launcher pattern from dagster-aws/dagster-docker
        # Strip container context to reduce payload size
        repository_origin = job_origin.repository_origin
        stripped_repository_origin = repository_origin._replace(container_context={})

        # Fix entry_point to use executable_path with python -m dagster
        # This handles the case where entry_point is just ["dagster"] but dagster
        # is installed in a virtualenv and not in the system PATH
        executable_path = repository_origin.executable_path
        if executable_path:
            # Use the Python executable with -m flag to invoke dagster module
            fixed_entry_point = [executable_path, "-m", "dagster"]
            stripped_repository_origin = stripped_repository_origin._replace(entry_point=fixed_entry_point)
            logger.info(f"Using entry point from executable_path: {fixed_entry_point}")

        stripped_job_origin = job_origin._replace(repository_origin=stripped_repository_origin)

        # Create ExecuteRunArgs and use get_command_args() to build the command
        # This matches the pattern from Docker and ECS launchers
        # Now that the code location has dagster-cloud installed, we can use the full instance ref
        args = ExecuteRunArgs(
            job_origin=stripped_job_origin,
            run_id=run_id,
            instance_ref=self._instance.get_ref(),
        )

        # Use the built-in method to generate the command
        # This will include the correct entry point from job_origin
        command = args.get_command_args()

        logger.info(f"Run {run_id} will execute with command: {command}")

        # Configure ACR registry credentials if using ACR
        registries = None
        registry_server = container_image.split('/')[0] if '/' in container_image else None
        if registry_server and 'azurecr.io' in registry_server:
            logger.info(f"Configuring ACR access for run: {registry_server}")
            registries = [
                RegistryCredentials(
                    server=registry_server,
                    identity=self.code_server_identity_id
                )
            ]

        # Create Container App for the run
        container_app = ContainerApp(
            location=self.location,
            managed_environment_id=self.environment_id,
            identity=ManagedServiceIdentity(
                type="UserAssigned",
                user_assigned_identities={self.code_server_identity_id: UserAssignedIdentity()}
            ) if self.code_server_identity_id else None,
            configuration=Configuration(
                # No ingress - runs don't need external access
                ingress=None,
                secrets=[],
                registries=registries,
                active_revisions_mode="Single",
            ),
            template=Template(
                containers=[
                    Container(
                        name="run-worker",
                        image=container_image,
                        resources=ContainerResources(
                            cpu=0.5,
                            memory="1.0Gi"
                        ),
                        env=env_vars,
                        # Set the command to execute the run using dagster api execute_run
                        command=command
                    )
                ],
                scale=Scale(
                    min_replicas=0,  # Scale to 0 when done
                    max_replicas=1,
                    rules=[]
                )
            ),
            tags={
                **self.required_tags,
                "dagster-deployment": deployment_name,
                "dagster-location": location_name,
                "dagster-component": "run-worker",
                "dagster-run-id": run_id,
                "managed-by": "dagster-cloud-agent",
            }
        )

        try:
            # Create the Container App
            poller = self.aca_client.container_apps.begin_create_or_update(
                resource_group_name=self.resource_group,
                container_app_name=app_name,
                container_app_envelope=container_app
            )

            # Don't wait for completion - return immediately
            # The run will execute asynchronously
            logger.info(f"Run {run_id} Container App creation started: {app_name}")

        except Exception as e:
            logger.error(f"Failed to launch run {run_id}: {e}")
            raise

    def terminate(self, run_id):
        """
        Terminate a running job by deleting its Container App.
        """
        app_name = f"dagster-run-{run_id[:8]}"
        app_name = app_name.lower().replace("_", "-")

        try:
            logger.info(f"Terminating run {run_id} by deleting Container App {app_name}")
            self.aca_client.container_apps.begin_delete(
                resource_group_name=self.resource_group,
                container_app_name=app_name
            )
        except Exception as e:
            logger.warning(f"Failed to terminate run {run_id}: {e}")


class AcaServerHandle(NamedTuple):
    """Handle representing an Azure Container App code server."""
    app_name: str
    deployment_name: str
    location_name: str
    agent_id: Optional[str]
    update_timestamp: float


class AcaUserCodeLauncher(DagsterCloudUserCodeLauncher):
    """
    Dagster Cloud user code launcher that deploys code servers to Azure Container Apps.

    This launcher creates Container Apps (not ACI) for code servers, providing:
    - Zero-downtime deployments via ACA's built-in blue-green
    - Automatic health checks and auto-healing
    - Integrated monitoring and logging
    - Consistent platform (all on ACA)

    Configuration (dagster.yaml):
        user_code_launcher:
          module: aca_launcher
          class: AcaUserCodeLauncher
          config:
            subscription_id: YOUR_SUBSCRIPTION_ID
            resource_group: dagster-aca-rg
            environment_name: dagster-aca-env
            location: eastus
            cpu: 0.5
            memory: 1.0Gi
    """

    def __init__(self, inst_data=None, **kwargs):
        """
        Initialize the ACA launcher with Azure credentials and configuration.

        Args:
            inst_data: ConfigurableClassData instance (for Dagster serialization)
            **kwargs: Configuration parameters from dagster.yaml
        """
        # Call parent constructor with NO parameters - use all defaults
        # This ensures proper base class initialization without overriding behavior
        super().__init__()

        self._inst_data = inst_data

        # Extract config from inst_data or use kwargs directly
        config = inst_data.config_dict if inst_data else kwargs

        # Helper function to expand environment variables if in ${VAR:default} format
        def _expand_env_var(value, env_var_name, default):
            if isinstance(value, str) and value.startswith("${") and value.endswith("}"):
                # Value is in ${VAR:default} format - read from environment instead
                return os.getenv(env_var_name, default)
            return value or os.getenv(env_var_name, default)

        self.subscription_id = _expand_env_var(config.get("subscription_id"), "AZURE_SUBSCRIPTION_ID", None)
        self.resource_group = _expand_env_var(config.get("resource_group"), "AGENT_RESOURCE_GROUP", "dagster-aca-rg")
        self.environment_name = _expand_env_var(config.get("environment_name"), "ENVIRONMENT_NAME", "dagster-aca-env")
        self.location = _expand_env_var(config.get("location"), "AZURE_LOCATION", "eastus")
        self.cpu = config.get("cpu", 0.5)
        self.memory = config.get("memory", "1.0Gi")

        # Azure policy-required tags (can be configured via environment or config)
        self.required_tags = config.get("tags", {})
        # Add Department tag if not present (required by Azure policy)
        if "Department" not in self.required_tags:
            self.required_tags["Department"] = os.getenv("AZURE_TAG_DEPARTMENT", "Engineering")

        # Container registry authentication
        # ACR (Azure Container Registry) uses managed identity - no credentials needed
        # Other registries are not supported for hybrid deployments

        # Code server managed identity (for pulling from ACR)
        # This identity is created by the Bicep template and has AcrPull permissions
        self.code_server_identity_id = os.getenv("CODE_SERVER_IDENTITY_ID")
        if self.code_server_identity_id:
            logger.info(f"Code server identity configured: {self.code_server_identity_id}")
        else:
            logger.warning(
                "CODE_SERVER_IDENTITY_ID not set. Code servers will not have managed identity. "
                "This may prevent pulling images from ACR."
            )

        # Azure Container Apps client
        self.credential = DefaultAzureCredential()
        self.aca_client = ContainerAppsAPIClient(
            credential=self.credential,
            subscription_id=self.subscription_id
        )

        # Get managed environment ID
        self.environment_id = self._get_environment_id()

        logger.info(
            f"Initialized AcaUserCodeLauncher: rg={self.resource_group}, "
            f"env={self.environment_name}, cpu={self.cpu}, memory={self.memory}"
        )

    @property
    def inst_data(self):
        return self._inst_data

    @classmethod
    def config_type(cls):
        return {
            "subscription_id": str,
            "resource_group": str,
            "environment_name": str,
            "location": str,
            "cpu": float,
            "memory": str,
        }

    @classmethod
    def from_config_value(cls, inst_data, config_value):
        """Create an instance from configuration data."""
        return cls(inst_data=inst_data, **config_value)

    def _get_environment_id(self) -> str:
        """Get the full resource ID of the Container Apps environment."""
        return (
            f"/subscriptions/{self.subscription_id}"
            f"/resourceGroups/{self.resource_group}"
            f"/providers/Microsoft.App/managedEnvironments/{self.environment_name}"
        )

    def _get_registry_credentials(self, image: str) -> tuple[list[Secret], list[RegistryCredentials]]:
        """
        Build registry credentials for pulling a container image.

        For hybrid deployments, only Azure Container Registry (ACR) is supported.
        ACR uses managed identity authentication - no credentials needed.

        Args:
            image: Container image URL (e.g., "myacr.azurecr.io/dagster-code:latest")

        Returns:
            Tuple of (secrets list, registries list) for Container App configuration
        """
        # Extract registry server from image URL
        # Format: registry.com/repo:tag or registry.com:port/repo:tag
        registry_server = image.split('/')[0] if '/' in image else None

        if not registry_server:
            # No registry specified (e.g., "ubuntu:latest") - use Docker Hub public
            return [], []

        # Check if this is Azure Container Registry (ACR)
        if 'azurecr.io' in registry_server:
            logger.info(f"Using Azure Container Registry {registry_server} with managed identity")
            # ACR with managed identity - configure registry to use the managed identity
            # The Container App's managed identity must have AcrPull role on the ACR
            if not self.code_server_identity_id:
                raise ValueError(
                    "CODE_SERVER_IDENTITY_ID environment variable not set. "
                    "Managed identity is required for ACR authentication."
                )

            registries = [
                RegistryCredentials(
                    server=registry_server,
                    identity=self.code_server_identity_id  # Use managed identity for authentication
                )
            ]
            return [], registries

        # Check if this is AWS ECR (serverless mode - not supported for hybrid)
        if 'ecr' in registry_server and 'amazonaws.com' in registry_server:
            raise ValueError(
                f"Code location uses AWS ECR image ({registry_server}). "
                "This indicates the code location is configured for Dagster Cloud Serverless mode. "
                "For hybrid deployments with Azure Container Apps, please:\n"
                "1. Build and push your code location image to Azure Container Registry (ACR)\n"
                "2. Update the code location in Dagster Cloud to use the ACR image\n"
                "3. Grant the agent's managed identity 'AcrPull' role on your ACR"
            )

        # Other registries not supported
        raise ValueError(
            f"Unsupported container registry: {registry_server}. "
            "Azure Container Apps hybrid agent only supports Azure Container Registry (ACR). "
            "Please push your image to ACR and update your code location configuration."
        )

    def launch_code_server(
        self,
        deployment_name: str,
        location_name: str,
        image: str,
        environment_variables: Optional[Dict[str, str]] = None,
        container_context: Optional[Dict] = None
    ) -> str:
        """
        Launch a Dagster code server as an Azure Container App.

        Args:
            deployment_name: Dagster deployment name (e.g., "prod")
            location_name: Code location name (e.g., "my_dagster_project")
            image: Container image URL (e.g., "myacr.azurecr.io/dagster-code:latest")
            environment_variables: Environment variables to pass to container
            container_context: Additional ACA-specific configuration

        Returns:
            Container App name (used to track/manage the app)
        """
        # Generate Container App name
        # Format: dagster-{deployment}-{location}
        # Sanitize for ACA naming rules (lowercase alphanumeric and hyphens, max 32 chars)
        app_name = f"dagster-{deployment_name}-{location_name}"[:32]
        app_name = app_name.lower().replace("_", "-")

        logger.info(
            f"Launching code server: deployment={deployment_name}, "
            f"location={location_name}, image={image}, app={app_name}"
        )

        # Build environment variables
        env_vars = self._build_environment_variables(
            deployment_name, location_name, environment_variables
        )

        # Apply container_context overrides if provided
        cpu = self.cpu
        memory = self.memory
        if container_context:
            cpu = container_context.get("cpu", cpu)
            memory = container_context.get("memory", memory)

        # Get registry credentials for pulling the image
        secrets, registries = self._get_registry_credentials(image)

        # Create Container App configuration
        container_app = ContainerApp(
            location=self.location,
            managed_environment_id=self.environment_id,
            # Assign code server managed identity for ACR access
            identity=ManagedServiceIdentity(
                type="UserAssigned",
                user_assigned_identities={self.code_server_identity_id: UserAssignedIdentity()}
            ) if self.code_server_identity_id else None,
            configuration=Configuration(
                # No ingress needed - code servers communicate via internal gRPC
                ingress=None,
                # Registry credentials (if needed for private registries)
                secrets=secrets,
                registries=registries if registries else None,
                # Revisions mode: Single (rolling updates)
                # For zero-downtime: use Multiple
                active_revisions_mode="Single",
            ),
            template=Template(
                containers=[
                    Container(
                        name="code-server",
                        image=image,
                        resources=ContainerResources(
                            cpu=cpu,
                            memory=memory
                        ),
                        env=env_vars,
                        # Code servers typically expose port 4000 for gRPC
                        # No need to expose publicly - internal only
                    )
                ],
                scale=Scale(
                    min_replicas=1,  # Always running
                    max_replicas=1,  # Single instance per code location
                    # No scale rules - code servers don't auto-scale
                    rules=[]
                )
            ),
            # Tags for tracking and management
            tags={
                **self.required_tags,  # Include policy-required tags (e.g., Department)
                "dagster-deployment": deployment_name,
                "dagster-location": location_name,
                "dagster-component": "code-server",
                "managed-by": "dagster-cloud-agent"
            }
        )

        try:
            # Check if Container App already exists
            existing_app = None
            try:
                existing_app = self.aca_client.container_apps.get(
                    resource_group_name=self.resource_group,
                    container_app_name=app_name
                )
                logger.info(f"Container App {app_name} already exists, updating...")
            except Exception:
                logger.info(f"Container App {app_name} does not exist, creating...")

            # Create or update the Container App
            poller = self.aca_client.container_apps.begin_create_or_update(
                resource_group_name=self.resource_group,
                container_app_name=app_name,
                container_app_envelope=container_app
            )

            # Wait for creation/update to complete (typically 30-60 seconds)
            result = poller.result(timeout=180)

            logger.info(
                f"Successfully launched code server: {app_name} "
                f"(provisioning_state={result.provisioning_state})"
            )

            return app_name

        except Exception as e:
            logger.error(f"Failed to launch code server {app_name}: {e}")
            raise

    def update_code_server(
        self,
        app_name: str,
        image: str,
        environment_variables: Optional[Dict[str, str]] = None
    ):
        """
        Update an existing code server with a new image (code deployment).

        This triggers ACA's built-in blue-green deployment:
        1. New revision created with updated image
        2. Health checks performed
        3. Traffic gradually shifted to new revision
        4. Old revision deactivated

        Args:
            app_name: Container App name
            image: New container image URL
            environment_variables: Updated environment variables
        """
        logger.info(f"Updating code server: {app_name} with image {image}")

        try:
            # Get existing app
            existing_app = self.aca_client.container_apps.get(
                resource_group_name=self.resource_group,
                container_app_name=app_name
            )

            # Update container image
            existing_app.template.containers[0].image = image

            # Update environment variables if provided
            if environment_variables:
                env_vars = []
                for key, value in environment_variables.items():
                    env_vars.append(EnvironmentVar(name=key, value=value))
                existing_app.template.containers[0].env = env_vars

            # Apply update (triggers blue-green deployment)
            poller = self.aca_client.container_apps.begin_create_or_update(
                resource_group_name=self.resource_group,
                container_app_name=app_name,
                container_app_envelope=existing_app
            )

            result = poller.result(timeout=180)

            logger.info(
                f"Successfully updated code server: {app_name} "
                f"(provisioning_state={result.provisioning_state})"
            )

        except Exception as e:
            logger.error(f"Failed to update code server {app_name}: {e}")
            raise

    def terminate_code_server(self, app_name: str):
        """
        Terminate a code server by deleting the Container App.

        Note: Typically, code servers are long-lived and NOT terminated.
        This method exists for cleanup scenarios (e.g., code location deleted).

        Args:
            app_name: Container App name to delete
        """
        logger.info(f"Terminating code server: {app_name}")

        try:
            poller = self.aca_client.container_apps.begin_delete(
                resource_group_name=self.resource_group,
                container_app_name=app_name
            )
            poller.result(timeout=120)
            logger.info(f"Successfully terminated code server: {app_name}")

        except Exception as e:
            logger.error(f"Failed to terminate code server {app_name}: {e}")
            raise

    def get_code_server_status(self, app_name: str) -> Dict:
        """
        Get the status of a code server Container App.

        Args:
            app_name: Container App name

        Returns:
            Dictionary with status information
        """
        try:
            app = self.aca_client.container_apps.get(
                resource_group_name=self.resource_group,
                container_app_name=app_name
            )

            # Get latest revision status
            latest_revision = app.latest_revision_name
            revision_fqdn = app.latest_revision_fqdn if hasattr(app, 'latest_revision_fqdn') else None

            return {
                "name": app_name,
                "provisioning_state": app.provisioning_state,
                "latest_revision": latest_revision,
                "latest_ready": app.latest_ready_revision_name if hasattr(app, 'latest_ready_revision_name') else None,
                "running_status": app.running_status if hasattr(app, 'running_status') else "Unknown",
                "fqdn": revision_fqdn,
            }

        except Exception as e:
            logger.warning(f"Failed to get status for {app_name}: {e}")
            return {"name": app_name, "error": str(e)}

    def list_code_servers(self, deployment_name: Optional[str] = None) -> List[Dict]:
        """
        List all code server Container Apps, optionally filtered by deployment.

        Args:
            deployment_name: Optional deployment name to filter by

        Returns:
            List of Container App information
        """
        try:
            apps = self.aca_client.container_apps.list_by_resource_group(
                resource_group_name=self.resource_group
            )

            results = []
            for app in apps:
                # Filter by Dagster tags
                if app.tags and app.tags.get("managed-by") == "dagster-cloud-agent":
                    if deployment_name and app.tags.get("dagster-deployment") != deployment_name:
                        continue

                    results.append({
                        "name": app.name,
                        "deployment": app.tags.get("dagster-deployment"),
                        "location": app.tags.get("dagster-location"),
                        "provisioning_state": app.provisioning_state,
                        "latest_revision": app.latest_revision_name,
                    })

            return results

        except Exception as e:
            logger.error(f"Failed to list code servers: {e}")
            return []

    def _build_environment_variables(
        self,
        deployment_name: str,
        location_name: str,
        custom_env: Optional[Dict[str, str]] = None
    ) -> List[EnvironmentVar]:
        """
        Build environment variables list for the code server container.

        Args:
            deployment_name: Dagster deployment name
            location_name: Code location name
            custom_env: Additional environment variables

        Returns:
            List of EnvironmentVar objects
        """
        env_vars = [
            EnvironmentVar(name="DAGSTER_CLOUD_DEPLOYMENT_NAME", value=deployment_name),
            EnvironmentVar(name="DAGSTER_CLOUD_CODE_LOCATION_NAME", value=location_name),
            EnvironmentVar(
                name="DAGSTER_CLOUD_URL",
                value=os.getenv("DAGSTER_CLOUD_URL", "https://dagster.cloud")
            ),
        ]

        # Add custom environment variables
        if custom_env:
            for key, value in custom_env.items():
                env_vars.append(EnvironmentVar(name=key, value=value))

        return env_vars

    def scale_code_server(self, app_name: str, min_replicas: int = 1, max_replicas: int = 1):
        """
        Scale a code server (change replica count).

        Typically, code servers run with 1 replica, but this allows scaling
        for high-availability or load distribution.

        Args:
            app_name: Container App name
            min_replicas: Minimum replicas
            max_replicas: Maximum replicas
        """
        logger.info(f"Scaling code server {app_name}: min={min_replicas}, max={max_replicas}")

        try:
            # Get existing app
            app = self.aca_client.container_apps.get(
                resource_group_name=self.resource_group,
                container_app_name=app_name
            )

            # Update scale configuration
            app.template.scale.min_replicas = min_replicas
            app.template.scale.max_replicas = max_replicas

            # Apply update
            poller = self.aca_client.container_apps.begin_create_or_update(
                resource_group_name=self.resource_group,
                container_app_name=app_name,
                container_app_envelope=app
            )

            poller.result(timeout=120)
            logger.info(f"Successfully scaled code server: {app_name}")

        except Exception as e:
            logger.error(f"Failed to scale code server {app_name}: {e}")
            raise

    def get_code_server_logs(self, app_name: str, tail: int = 100) -> str:
        """
        Get recent logs from a code server.

        Note: This requires Azure CLI or direct Log Analytics queries.
        For now, returns instructions for accessing logs.

        Args:
            app_name: Container App name
            tail: Number of recent lines to retrieve

        Returns:
            Log content or instructions
        """
        return f"""
To view logs for {app_name}, use:

  az containerapp logs show -n {app_name} -g {self.resource_group} --tail {tail} --follow

Or query Log Analytics:
  az monitor log-analytics query \\
    --workspace {self.resource_group} \\
    --analytics-query "ContainerAppConsoleLogs_CL | where ContainerAppName_s == '{app_name}' | top {tail} by TimeGenerated desc"
"""

    # =========================================================================
    # Abstract Method Implementations (Required by DagsterCloudUserCodeLauncher)
    # =========================================================================

    def _get_standalone_dagster_server_handles_for_location(
        self, deployment_name: str, location_name: str
    ) -> Collection[AcaServerHandle]:
        """
        Return a list of handles representing all running servers for a given location.

        This method is called during reconciliation to discover existing code servers.
        """
        handles = []
        try:
            # List all Container Apps in the resource group
            apps = self.aca_client.container_apps.list_by_resource_group(
                resource_group_name=self.resource_group
            )

            # Filter for code servers matching this deployment and location
            for app in apps:
                if not app.tags or app.tags.get("managed-by") != "dagster-cloud-agent":
                    continue

                if (app.tags.get("dagster-deployment") == deployment_name and
                    app.tags.get("dagster-location") == location_name):

                    # Extract metadata from tags
                    agent_id = app.tags.get("dagster-agent-id")
                    update_timestamp_str = app.tags.get("dagster-update-timestamp")
                    update_timestamp = float(update_timestamp_str) if update_timestamp_str else time.time()

                    handles.append(AcaServerHandle(
                        app_name=app.name,
                        deployment_name=deployment_name,
                        location_name=location_name,
                        agent_id=agent_id,
                        update_timestamp=update_timestamp
                    ))

            return handles

        except Exception as e:
            logger.error(
                f"Failed to get server handles for {deployment_name}:{location_name}: {e}"
            )
            return []

    def _list_server_handles(self) -> List[AcaServerHandle]:
        """
        Return a list of all server handles across all deployments and locations.

        Used for cleanup operations.
        """
        handles = []
        try:
            # List all Container Apps in the resource group
            apps = self.aca_client.container_apps.list_by_resource_group(
                resource_group_name=self.resource_group
            )

            # Filter for Dagster-managed code servers
            for app in apps:
                if not app.tags or app.tags.get("managed-by") != "dagster-cloud-agent":
                    continue

                deployment_name = app.tags.get("dagster-deployment", "unknown")
                location_name = app.tags.get("dagster-location", "unknown")
                agent_id = app.tags.get("dagster-agent-id")
                update_timestamp_str = app.tags.get("dagster-update-timestamp")
                update_timestamp = float(update_timestamp_str) if update_timestamp_str else time.time()

                handles.append(AcaServerHandle(
                    app_name=app.name,
                    deployment_name=deployment_name,
                    location_name=location_name,
                    agent_id=agent_id,
                    update_timestamp=update_timestamp
                ))

            return handles

        except Exception as e:
            logger.error(f"Failed to list server handles: {e}")
            return []

    def _remove_server_handle(self, server_handle: AcaServerHandle) -> None:
        """
        Shut down resources associated with the given handle.

        This deletes the Container App.
        """
        logger.info(f"Removing server: {server_handle.app_name}")
        try:
            self.terminate_code_server(server_handle.app_name)
        except Exception as e:
            logger.error(f"Failed to remove server {server_handle.app_name}: {e}")
            raise

    def _start_new_server_spinup(
        self,
        deployment_name: str,
        location_name: str,
        desired_entry: UserCodeLauncherEntry,
    ) -> DagsterCloudGrpcServer:
        """
        Create a new server for the given location and return a handle.

        This method starts the server creation but doesn't wait for it to be ready.
        Waiting happens in _wait_for_new_server_ready.
        """
        code_location_deploy_data = desired_entry.code_location_deploy_data
        image = code_location_deploy_data.image

        if not image:
            raise ValueError(
                f"No image specified for {deployment_name}:{location_name}. "
                "Azure Container Apps launcher requires container images."
            )

        # Generate Container App name
        app_name = f"dagster-{deployment_name}-{location_name}"[:32]
        app_name = app_name.lower().replace("_", "-")

        logger.info(
            f"Starting server spinup: deployment={deployment_name}, "
            f"location={location_name}, image={image}, app={app_name}"
        )

        # Build environment variables
        env_vars = self._build_environment_variables(
            deployment_name,
            location_name,
            code_location_deploy_data.cloud_context_env
        )

        # Get resource configuration
        container_context = code_location_deploy_data.container_context or {}
        cpu = container_context.get("cpu", self.cpu)
        memory = container_context.get("memory", self.memory)

        # Get agent ID for tracking
        agent_id = self._instance.instance_uuid if hasattr(self, '_instance') and self._instance else None

        # Get registry credentials for pulling the image
        secrets, registries = self._get_registry_credentials(image)

        # Create Container App configuration
        container_app = ContainerApp(
            location=self.location,
            managed_environment_id=self.environment_id,
            # Assign code server managed identity for ACR access
            identity=ManagedServiceIdentity(
                type="UserAssigned",
                user_assigned_identities={self.code_server_identity_id: UserAssignedIdentity()}
            ) if self.code_server_identity_id else None,
            configuration=Configuration(
                # Enable ingress for gRPC communication with VNET
                ingress=Ingress(
                    external=True,  # External ingress for VNET connectivity
                    target_port=4000,  # Standard Dagster gRPC port
                    transport="tcp",  # TCP transport for direct gRPC connection
                ),
                # Registry credentials (if needed for private registries)
                secrets=secrets,
                registries=registries if registries else None,
                active_revisions_mode="Single",
            ),
            template=Template(
                containers=[
                    Container(
                        name="code-server",
                        image=image,
                        resources=ContainerResources(
                            cpu=cpu,
                            memory=memory
                        ),
                        env=env_vars,
                    )
                ],
                scale=Scale(
                    min_replicas=1,
                    max_replicas=1,
                    rules=[]
                )
            ),
            tags={
                **self.required_tags,  # Include policy-required tags (e.g., Department)
                "dagster-deployment": deployment_name,
                "dagster-location": location_name,
                "dagster-component": "code-server",
                "managed-by": "dagster-cloud-agent",
                "dagster-agent-id": agent_id or "unknown",
                "dagster-update-timestamp": str(desired_entry.update_timestamp),
            }
        )

        try:
            # Start the Container App creation (async operation)
            poller = self.aca_client.container_apps.begin_create_or_update(
                resource_group_name=self.resource_group,
                container_app_name=app_name,
                container_app_envelope=container_app
            )

            # Wait for the initial creation to start
            # (We'll wait for full readiness in _wait_for_new_server_ready)
            result = poller.result(timeout=180)

            logger.info(
                f"Server spinup started: {app_name} "
                f"(provisioning_state={result.provisioning_state})"
            )

            # Create server handle
            server_handle = AcaServerHandle(
                app_name=app_name,
                deployment_name=deployment_name,
                location_name=location_name,
                agent_id=agent_id,
                update_timestamp=desired_entry.update_timestamp
            )

            # Get the Container App's FQDN for gRPC endpoint
            # The FQDN format is: <app-name>.<env-domain>
            app = self.aca_client.container_apps.get(
                resource_group_name=self.resource_group,
                container_app_name=app_name
            )

            # Use the app's FQDN if available, otherwise use app name
            host = app.configuration.ingress.fqdn if (
                app.configuration and
                app.configuration.ingress and
                app.configuration.ingress.fqdn
            ) else app_name

            # Determine the correct port based on ingress configuration
            # - TCP transport: Always use target port 4000 (exposes port directly)
            # - HTTP/2 transport with external ingress: Use port 443 (HTTPS)
            # - HTTP/2 transport with internal ingress: Use port 4000
            transport = (app.configuration and
                        app.configuration.ingress and
                        app.configuration.ingress.transport) or "tcp"
            is_external = (app.configuration and
                          app.configuration.ingress and
                          app.configuration.ingress.external)

            # TCP transport always uses target port (4000)
            # HTTP/2 external uses 443, HTTP/2 internal uses 4000
            if transport.lower() == "tcp":
                port = 4000
            elif is_external:
                port = 443
            else:
                port = 4000

            logger.info(f"Connecting to {host}:{port} (transport={transport}, external={is_external})")

            server_endpoint = ServerEndpoint(
                host=host,
                port=port,
                socket=None,
            )

            return DagsterCloudGrpcServer(
                server_handle=server_handle,
                server_endpoint=server_endpoint,
                code_location_deploy_data=code_location_deploy_data
            )

        except Exception as e:
            logger.error(f"Failed to start server spinup for {app_name}: {e}")
            raise

    async def _wait_for_new_server_ready(
        self,
        deployment_name: str,
        location_name: str,
        desired_entry: UserCodeLauncherEntry,
        server_handle: AcaServerHandle,
        server_endpoint: ServerEndpoint,
    ) -> None:
        """
        Wait for a newly-created server to be ready to serve requests.

        This polls the Container App status until it's running and healthy.
        """
        logger.info(
            f"Waiting for server to be ready: {server_handle.app_name} "
            f"at {server_endpoint.host}:{server_endpoint.port}"
        )

        max_attempts = 60  # 5 minutes with 5-second intervals
        attempt = 0

        while attempt < max_attempts:
            try:
                # Check Container App status
                app = self.aca_client.container_apps.get(
                    resource_group_name=self.resource_group,
                    container_app_name=server_handle.app_name
                )

                # Check if app is provisioned and running
                if (app.provisioning_state == "Succeeded" and
                    hasattr(app, 'running_status') and
                    app.running_status == "Running"):

                    # Try to connect to the gRPC server
                    try:
                        client = server_endpoint.create_client()
                        # Simple health check - try to list repositories
                        await asyncio.get_event_loop().run_in_executor(
                            None,
                            lambda: client.health_check_query()
                        )
                        logger.info(
                            f"Server is ready: {server_handle.app_name}"
                        )
                        return
                    except Exception as e:
                        logger.info(
                            f"Server not yet responding to gRPC (attempt {attempt + 1}): {e}"
                        )

                # Still provisioning or starting up
                logger.info(
                    f"Server not ready yet (attempt {attempt + 1}): "
                    f"provisioning_state={app.provisioning_state}, "
                    f"running_status={getattr(app, 'running_status', 'Unknown')}"
                )

            except Exception as e:
                logger.info(
                    f"Error checking server status (attempt {attempt + 1}): {e}"
                )

            attempt += 1
            await asyncio.sleep(5)

        raise TimeoutError(
            f"Server {server_handle.app_name} did not become ready within "
            f"{max_attempts * 5} seconds"
        )

    def get_agent_id_for_server(self, handle: AcaServerHandle) -> Optional[str]:
        """
        Returns the agent_id that created a particular gRPC server.
        """
        return handle.agent_id

    def get_code_server_resource_limits(
        self, deployment_name: str, location_name: str
    ) -> CloudContainerResourceLimits:
        """
        Return the resource limits for a code server.

        For ACA, we return empty limits as ACA manages resources differently.
        """
        # ACA doesn't use the same resource limit structure as ECS/K8s
        # Return an empty CloudContainerResourceLimits
        return CloudContainerResourceLimits()

    def get_server_create_timestamp(self, handle: AcaServerHandle) -> Optional[float]:
        """
        Returns the update_timestamp value from the given code server.
        """
        return handle.update_timestamp

    @property
    def requires_images(self) -> bool:
        """
        Whether this launcher requires container images.

        Azure Container Apps always require images.
        """
        return True

    def run_launcher(self) -> AcaRunLauncher:
        """
        Return the run launcher to use for executing runs.

        For Dagster Cloud, runs are executed in separate containers from code servers,
        but use the same container image. The run launcher creates temporary Container Apps
        for each run execution.
        """
        launcher = AcaRunLauncher()
        launcher.register_instance(self._instance)
        return launcher

    @property
    def user_code_deployment_type(self) -> UserCodeDeploymentType:
        """
        Return the deployment type for telemetry/reporting.

        We use DOCKER as the closest match for Container Apps.
        """
        return UserCodeDeploymentType.DOCKER

