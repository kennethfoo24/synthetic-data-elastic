# Network Topology MCP App

An [MCP](https://modelcontextprotocol.io/) server that exposes a single tool — `network-topology` — which queries your Elastic project and returns an interactive prod/DR network map. The map is rendered inline in Claude Code (and any MCP-compatible client) as a force-directed graph.

**The tool reads only data that was already ingested by the platform.** It never reads `topology/network.yaml` or any local config file; the only data source is Elasticsearch.

---

## Prerequisites

- **Node.js 20+** (`node --version`)
- A running Elastic Serverless Observability project with data already flowing (`make validate` at the repo root should pass)
- The three env vars described below

---

## Setup

```bash
cd mcp-app
npm install --legacy-peer-deps   # install dependencies
npm run build                    # compile TypeScript + build the UI bundle
```

The build produces two artefacts:
- `dist/server.js` — the MCP stdio server
- `dist-ui/index.html` — the self-contained React graph UI (injected at runtime)

---

## Environment variables

The MCP server uses the same three variables as the repo root `.env`:

| Variable | Description | Example |
|---|---|---|
| `ES_URL` | Elasticsearch endpoint (no trailing slash) | `https://my-project.es.io:9243` |
| `KIBANA_URL` | Kibana endpoint (no trailing slash) | `https://my-project.kb.io:9243` |
| `ELASTIC_API_KEY` | Elastic API key with read access | `abc123==` |

Copy values from the repo root `.env` file (or from `.env.example` and fill in your own).

---

## Registering with Claude Code

Run the following command once, replacing the placeholders:

```bash
claude mcp add network-topology \
  --env ES_URL=<your-es-url> \
  --env KIBANA_URL=<your-kibana-url> \
  --env ELASTIC_API_KEY=<your-api-key> \
  -- node /absolute/path/to/mcp-app/dist/server.js
```

**Tip:** if you have already exported the variables in your shell, you can omit the `--env` flags and just pass them through the environment:

```bash
export ES_URL=https://my-project.es.io:9243
export KIBANA_URL=https://my-project.kb.io:9243
export ELASTIC_API_KEY=abc123==

claude mcp add network-topology -- node /absolute/path/to/mcp-app/dist/server.js
```

To confirm registration:

```bash
claude mcp list
```

---

## Example invocations

Ask Claude any of the following (or anything similar):

```
show me the network topology
```

```
show just the DR site over the last 24 hours
```

```
focus on cisco-rtr-core-01
```

```
what devices are connected to fw-prod-01?
```

---

## Tool arguments

The `network-topology` tool accepts these optional arguments:

| Argument | Type | Default | Description |
|---|---|---|---|
| `site` | `"production"` \| `"dr"` \| `"all"` | `"all"` | Filter the map to one site |
| `time_range` | string (ES expression) | `"now-1h"` | Lookback window for health and traffic data. Examples: `"now-24h"`, `"now-7d"` |
| `focus_device` | string | _(none)_ | Device name or ID. When set, returns only this device and its 1-hop neighbours |

---

## What you'll see

Claude renders the topology as a force-directed graph with:

- **Uniform node sizes** — every device is the same size so the layout stays readable even with 20+ nodes
- **Role glyphs** — a letter or icon in each node indicates the device role (R = router, S = switch, F = firewall, AP = access point, …)
- **Health rings** — a colour ring around each node shows current health: green (healthy), amber (degraded), red (critical), grey (no data)
- **Dashed cross-site edges** — VPN tunnels, storage replication links, and backup paths between production and DR are shown as dashed lines to distinguish them from intra-site traffic
- **Side panel** — clicking a node opens a side panel with device metadata and Kibana deep links:
  - **Logs** → Kibana Discover filtered to that device's logs
  - **Metrics** → Kibana filtered to SNMP/interface metrics for that device
  - **Alerts** → Kibana Alerts view filtered to the device

A live-verified example (2026-08-11): **26 nodes / 28 edges / 6 cross-site edges**, 18 production nodes and 8 DR nodes, zero warnings.

---

## Troubleshooting

**Empty map or "no nodes found"**

Data has not yet been ingested, or the time range is too narrow. Run `make validate` at the repo root to confirm data is flowing, then retry with a wider window:

```
show me the network topology for the last 24 hours
```

**Configuration error / auth error**

Check that `ES_URL`, `KIBANA_URL`, and `ELASTIC_API_KEY` are set correctly. The API key must have at least read access to the `metrics-*`, `logs-*`, and `filebeat-*` index patterns.

**UI not rendering (text-only response)**

If the build step was skipped, the server returns a text-only summary. Run `npm run build` inside `mcp-app/` and restart the MCP server.

**TypeScript errors on build**

Make sure you are on Node 20+. Run `npm install --legacy-peer-deps` to ensure all devDependencies are installed before building.
