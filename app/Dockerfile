FROM python:3.12-slim
# The spire-agent binary doubles as a Workload API client: `spire-agent api fetch x509`.
COPY --from=ghcr.io/spiffe/spire-agent:1.14.0 /opt/spire/bin/spire-agent /usr/local/bin/spire-agent
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY *.py ./
ENV PYTHONUNBUFFERED=1 HOME=/tmp
