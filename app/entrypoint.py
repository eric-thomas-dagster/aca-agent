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


def main():
    vault_uri = os.getenv("KEY_VAULT_URI")
    secret_names_raw = os.getenv("KEY_VAULT_SECRET_NAMES", "")
    secret_names = [s for s in secret_names_raw.split(",") if s]

    if vault_uri and secret_names:
        logging.info("Attempting to fetch %d secrets from Key Vault %s", len(secret_names), vault_uri)
        _fetch_key_vault_secrets(vault_uri, secret_names)
    else:
        logging.info("Key Vault not configured or no secrets specified (KEY_VAULT_URI or KEY_VAULT_SECRET_NAMES missing)")

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
    logging.info("  - Deployment: %s", os.getenv("DAGSTER_CLOUD_DEPLOYMENT_NAME", "NOT SET"))
    logging.info("=" * 60)

    logging.info("Executing: %s", " ".join(agent_cmd))

    # Replace current process with dagster-cloud agent
    os.execvp("dagster-cloud", agent_cmd)


if __name__ == '__main__':
    main()
