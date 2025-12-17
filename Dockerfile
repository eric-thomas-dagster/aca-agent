FROM dagster/dagster-cloud-agent:latest

# Add Azure Key Vault support and our small entrypoint helper
COPY app /app
COPY requirements.txt /app/requirements.txt
WORKDIR /app
# Install additional packages needed to access Azure Key Vault
RUN pip install --no-cache-dir -r requirements.txt || true
RUN pip install --no-cache-dir azure-identity azure-keyvault-secrets || true

ENV PYTHONUNBUFFERED=1

CMD ["python", "entrypoint.py"]
