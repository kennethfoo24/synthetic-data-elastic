# Synthetic Network Observability Data Platform

This project generates synthetic network and infrastructure telemetry data for ingestion into an Elastic Serverless Observability project. Data is managed and shipped via Fleet-managed Elastic Agents, enabling realistic simulation and testing of observability pipelines, dashboards, and alerting rules.

For detailed design and architecture, see [docs/superpowers/specs/2026-08-10-synthetic-network-observability-design.md](docs/superpowers/specs/2026-08-10-synthetic-network-observability-design.md).

## Quick start

```bash
cp .env.example .env
make up
```

(Coming in later tasks.)
