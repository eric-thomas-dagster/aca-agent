# Samples and local testing

Run the docker build and run commands to test the minimal agent locally.

```bash
docker build -t dagster-aca-agent:local .
docker run --rm -e AGENT_NAME=local-agent dagster-aca-agent:local
```

Use `infra/deploy.sh` to push to an Azure Container Registry and create an ACA instance.
