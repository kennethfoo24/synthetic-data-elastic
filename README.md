# Synthetic Network Observability Data Platform

This project generates synthetic network and infrastructure telemetry data for ingestion into an Elastic Serverless Observability project. Data is managed and shipped via Fleet-managed Elastic Agents, enabling realistic simulation and testing of observability pipelines, dashboards, and alerting rules.

For detailed design and architecture, see [docs/superpowers/specs/2026-08-10-synthetic-network-observability-design.md](docs/superpowers/specs/2026-08-10-synthetic-network-observability-design.md).

## Quick start

```bash
make bootstrap           # create .venv and install deps (python3.12 required)
cp .env.example .env     # fill in ES_URL, KIBANA_URL, ELASTIC_API_KEY
make up                  # deploy to Kubernetes (k8s context must point at your cluster)
make validate            # confirm data is flowing (~2 min after make up)
```

To reset databases after a pod restart (emptyDir volumes are lost on restart):

```bash
make reset-databases
```
