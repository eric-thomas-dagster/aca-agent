#!/usr/bin/env python3
"""Entry point that fetches secrets from Azure Key Vault (if configured)
and then execs the Dagster Cloud agent.

Environment variables used:
- KEY_VAULT_URI: set by ARM/Bicep template to vault URI, e.g. https://<vault>.vault.azure.net/
- KEY_VAULT_SECRET_NAMES: optional comma-separated list of secret names to fetch

        For each configured entry, this script will fetch the secret value and set an
        environment variable in the container. Each entry in `KEY_VAULT_SECRET_NAMES`
        may be either:

        - a single secret name (e.g. `MY_SECRET`) in which case the environment
            variable with the same name will be set; or
        - a mapping of the form `secretName:ENV_VAR_NAME` (e.g. `kv-token:DOTOKEN`) in
            which case the secret named `secretName` will be fetched and the
            environment variable `ENV_VAR_NAME` will be set to the secret value.
"""

import os
import sys
import logging
from pathlib import Path
from typing import List

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


def _fetch_key_vault_secrets(vault_uri: str, secret_names: List[str]):
    try:
        from azure.identity import DefaultAzureCredential
        from azure.keyvault.secrets import SecretClient
    except Exception as e:
        logging.error("Azure SDK not available: %s", e)
        return

    if not secret_names:
        logging.info("No Key Vault secret names configured.")
        return

    cred = DefaultAzureCredential()
    client = SecretClient(vault_url=vault_uri, credential=cred)

    for entry in secret_names:
        entry = entry.strip()
        if not entry:
            continue

        # Allow mapping secretName:ENV_VAR_NAME
        if ':' in entry:
            secret_name, env_name = entry.split(':', 1)
            secret_name = secret_name.strip()
            env_name = env_name.strip()
        else:
            secret_name = entry
            env_name = entry

        try:
            logging.info("Fetching secret '%s' from Key Vault -> env %s", secret_name, env_name)
            secret = client.get_secret(secret_name)
            os.environ[env_name] = secret.value
            logging.info("Injected secret '%s' into environment as %s", secret_name, env_name)
        except Exception as e:
            logging.error("Failed to fetch secret '%s' from Key Vault: %s", secret_name, e)


def _expand_env_vars_in_yaml():
    """Expand environment variables in dagster.yaml before Dagster reads it."""
    import re

    yaml_path = "/app/dagster.yaml"
    try:
        with open(yaml_path, 'r') as f:
            content = f.read()

        # Pattern to match ${VAR} or ${VAR:default}
        def replace_env_var(match):
            var_expr = match.group(1)
            if ':' in var_expr:
                var_name, default = var_expr.split(':', 1)
            else:
                var_name = var_expr
                default = ''

            value = os.getenv(var_name.strip(), default.strip())
            logging.info("Expanding ${%s} -> %s", var_name, value if value else "(empty)")
            return value

        # Replace all ${VAR} and ${VAR:default} patterns
        expanded_content = re.sub(r'\$\{([^}]+)\}', replace_env_var, content)

        # Write back the expanded content
        with open(yaml_path, 'w') as f:
            f.write(expanded_content)

        logging.info("Successfully expanded environment variables in dagster.yaml")
    except Exception as e:
        logging.error("Failed to expand environment variables in dagster.yaml: %s", e)
        raise


def main():
    vault_uri = os.getenv("KEY_VAULT_URI")
    secret_names_raw = os.getenv("KEY_VAULT_SECRET_NAMES", "")
    secret_names = [s for s in secret_names_raw.split(",") if s]

    if vault_uri and secret_names:
        logging.info("Attempting to fetch %d secrets from Key Vault %s", len(secret_names), vault_uri)
        _fetch_key_vault_secrets(vault_uri, secret_names)
    else:
        logging.info("Key Vault not configured or no secrets specified (KEY_VAULT_URI or KEY_VAULT_SECRET_NAMES missing)")

    # Expand environment variables in dagster.yaml
    _expand_env_vars_in_yaml()

    # Set required environment variables for ACA launcher
    # Code servers will be created in the SAME resource group as the agent
    if not os.getenv("AGENT_RESOURCE_GROUP"):
        logging.warning("AGENT_RESOURCE_GROUP not set - will use default")

    # Ensure AZURE_SUBSCRIPTION_ID is set (needed by ACA launcher)
    if not os.getenv("AZURE_SUBSCRIPTION_ID"):
        logging.warning("AZURE_SUBSCRIPTION_ID not set - ACA launcher may fail!")

    # Set DAGSTER_HOME to current directory where dagster.yaml is located
    os.environ["DAGSTER_HOME"] = "/app"

    # Add /app to PYTHONPATH so aca_launcher module can be imported
    pythonpath = os.environ.get("PYTHONPATH", "")
    os.environ["PYTHONPATH"] = f"/app:{pythonpath}" if pythonpath else "/app"

    # Launch the real Dagster Cloud agent with our custom ACA launcher
    # The agent will read configuration from /app/dagster.yaml
    agent_cmd = ["dagster-cloud", "agent", "run"]

    logging.info("=" * 60)
    logging.info("Starting Dagster Cloud Agent with ACA Code Server Launcher")
    logging.info("=" * 60)
    logging.info("Configuration:")
    logging.info("  - DAGSTER_HOME: /app")
    logging.info("  - Config file: /app/dagster.yaml")
    logging.info("  - Subscription: %s", os.getenv("AZURE_SUBSCRIPTION_ID", "NOT SET"))
    logging.info("  - Agent RG: %s", os.getenv("AGENT_RESOURCE_GROUP"))
    logging.info("  - Environment: %s", os.getenv("ENVIRONMENT_NAME", "dagster-aca-env"))
    logging.info("  - Agent Name: %s", os.getenv("AGENT_NAME", "dagster-aca-agent"))
    logging.info("=" * 60)
    logging.info("Dagster Cloud Connection:")
    org_id = os.getenv("DAGSTER_CLOUD_ORG_ID", "NOT SET")
    deployment = os.getenv("DAGSTER_CLOUD_DEPLOYMENT_NAME", "NOT SET")
    token_set = "SET" if os.getenv("DAGSTER_CLOUD_API_TOKEN") else "NOT SET"
    logging.info("  - Org ID: %s", org_id)
    logging.info("  - Deployment: %s", deployment)
    logging.info("  - API Token: %s", token_set)

    # Construct and log the expected URL
    if org_id and org_id != "NOT SET":
        constructed_url = f"https://{org_id}.agent.dagster.cloud"
        logging.info("  - Constructed URL: %s", constructed_url)
        logging.info("  - GraphQL endpoint: %s/%s/graphql", constructed_url, deployment)
    else:
        logging.warning("  - WARNING: DAGSTER_CLOUD_ORG_ID not set! URL construction will fail!")

    logging.info("=" * 60)

    logging.info("Starting Dagster Cloud Agent programmatically")

    # Import and start the agent directly instead of exec'ing
    # This ensures our patches are active when the agent runs
    from dagster_cloud.agent.cli import run_local_agent_in_environment

    agent_logging_config = None  # Uses default logging configuration
    run_local_agent_in_environment(Path("/app"), agent_logging_config)


if __name__ == '__main__':
    main()
