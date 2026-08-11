# Plan 3: Network Topology MCP App — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Lean plan — each task states its contract and verification; implementers write tests to pin the contract.

**Goal:** A standalone TypeScript MCP app exposing one tool, `network-topology`, that queries the live Elastic data (NetFlow edges + SNMP/syslog node identity) and renders an interactive production/DR network map inline in Claude, with deep links into Kibana.

**Architecture:** `mcp-app/` — an MCP server (stdio) whose tool returns both structured JSON and an MCP-Apps HTML/React UI resource. Queries run via ES `_search`/ES|QL against `logs-netflow.log-*` (edges), `metrics-snmp.device-*` (node identity + health), and the syslog datasets (log volume per device). The map is built **entirely from ingested data** — it never reads `topology/network.yaml`, so a rendered map doubles as an end-to-end proof the pipeline works.

**Tech Stack:** TypeScript 5, `@modelcontextprotocol/sdk`, `@elastic/elasticsearch`, React 18 + `react-force-graph-2d` (or d3-force + canvas), Vite for the UI bundle, Vitest for tests. Node 20+.

## Global Constraints

- Package root `mcp-app/`, its own `package.json` (not part of the Python package). Python CI untouched; add a `mcp-app` job to `.github/workflows/validate.yaml` (install, typecheck, test, build).
- Config from env: `ES_URL`, `KIBANA_URL`, `ELASTIC_API_KEY` — same names as the repo's `.env`. Never log the key. No new secrets.
- **Data-derived only:** no import of `topology/network.yaml` anywhere in `mcp-app/`.
- Site classification from IP: `10.10.0.0/16` → `production`, `10.20.0.0/16` → `dr`, anything else → `external`.
- Uniform node sizes (explicit user decision); role conveyed by icon/color. Edge thickness ∝ bytes.
- Every ES query is time-bounded and size-capped; default window `now-1h`.
- Verified live field names (do NOT re-derive): NetFlow — `source.ip`, `destination.ip`, `network.bytes`, `network.packets`, `destination.port`, `network.transport`. SNMP — `device.name`, `device.vendor`, `device.role`, `device.site`, plus `snmp.*` OID-named metric fields. Syslog identity — `observer.hostname` (ASA), `host.hostname`/`log.source.address` (IOS/PANW/Meraki). Verify anything not on this list against live data before coding it.

---

### Task 1: Scaffold + Elasticsearch client + config

**Files:** `mcp-app/package.json`, `tsconfig.json`, `vitest.config.ts`, `.gitignore` additions, `src/config.ts`, `src/es.ts`; tests `test/config.test.ts`.

**Contract:**
- `loadConfig()` reads the three env vars, throws a clear error naming any missing one, strips trailing slashes, and never includes the key in error text (test this).
- `createEsClient(config)` returns an `@elastic/elasticsearch` Client with ApiKey auth and a 30s request timeout.
- `npm run typecheck`, `npm test`, `npm run build` all work from `mcp-app/`.

**Verify:** tests pass; `npm run build` emits `dist/`. Commit.

---

### Task 2: Topology queries (edges + nodes + health)

**Files:** `src/queries/edges.ts`, `src/queries/nodes.ts`, `src/queries/health.ts`, `src/types.ts`; tests with a mocked ES client.

**Contract:**
- `types.ts`: `Node { id: string; name: string; ip: string; site: 'production'|'dr'|'external'; role: string; vendor: string; health: 'ok'|'warn'|'crit'|'unknown'; logCount: number }`, `Edge { source: string; target: string; bytes: number; packets: number; topPorts: number[]; crossSite: boolean }`, `Topology { nodes: Node[]; edges: Edge[]; window: {from: string; to: string}; warnings: string[] }`.
- `fetchEdges(es, {from, to, site})`: composite/terms agg over `logs-netflow.log-*` grouping `source.ip` × `destination.ip`, summing `network.bytes`/`network.packets`, top 3 `destination.port`. Cap 500 pairs. `crossSite` = the two IPs classify to different non-external sites.
- `fetchNodes(es, {from, to})`: terms agg on `device.name` over `metrics-snmp.device-*` returning name/vendor/role/site plus latest doc per device (top_hits size 1) — this is the identity source. Additionally resolve any NetFlow IP with no SNMP match into a node with `role: 'unknown'` (so the map never drops an edge endpoint).
- `fetchHealth(es, nodes, window)`: from the latest SNMP doc per device derive `health` — crit if any `ifOperStatus != 1` or CPU-equivalent gauge > 90, warn if > 75, else ok; `unknown` when no SNMP data. Field lookup must tolerate the OID-named `snmp.*` keys (find by suffix match, e.g. a key ending in `hrProcessorLoad.1`).
- `fetchLogVolume(es, nodes, window)`: per-device doc counts across the syslog datasets, matched on `observer.hostname` OR `host.hostname` equal to the device name.
- Each function is pure w.r.t. the client (inject `es`), so tests mock responses. Empty results return empty arrays + a `warnings` entry, never throw.

**Verify:** unit tests with recorded-shape mock responses (happy, empty, partial-field). Commit.

---

### Task 3: Topology assembly + IP/site logic

**Files:** `src/topology.ts`, `src/sites.ts`; tests.

**Contract:**
- `classifySite(ip)` → `'production' | 'dr' | 'external'` per the CIDR constraint; unit-tested at boundaries (10.10.255.255, 10.20.0.0, 10.30.x, 203.0.113.x).
- `buildTopology({edges, nodes, health, logVolume})` merges into a `Topology`: node ids are device names when resolvable, else the IP; edges reference node ids (remapping IPs→names); drops self-edges; sorts nodes by site then name and edges by bytes desc for stable output.
- `warnings[]` populated for: no NetFlow data, no SNMP data, edges whose endpoints couldn't be named.
- Pure function, no I/O — fully unit tested.

**Verify:** tests incl. a realistic fixture (~20 nodes / ~28 edges shaped like live data) asserting node/edge counts, cross-site edge detection, and stable ordering. Commit.

---

### Task 4: Kibana deep links

**Files:** `src/links.ts`; tests.

**Contract:**
- `discoverLink(kibanaUrl, {deviceName, dataset, from, to})` → a Kibana Discover URL with `_g` time range and `_a` query filtering on the device (rison-encoded; use a tiny helper, no heavy dep).
- `dashboardLink(kibanaUrl, integration)` → the integration dashboard landing URL by integration key (`cisco_asa`, `cisco_ios`, `panw`, `cisco_meraki`, `mongodb`, `postgresql`, `netflow`); unknown key → the Dashboards list URL.
- `snmpDiscoverLink(kibanaUrl, deviceName, window)` → Discover on `metrics-snmp.device-*` filtered to that device.
- URLs must be encoded correctly (tests assert round-trippable query params and no unencoded spaces/quotes).

**Verify:** unit tests. Commit.

---

### Task 5: MCP server + `network-topology` tool

**Files:** `src/server.ts`, `src/tool.ts`; tests for the tool handler with a mocked ES client.

**Contract:**
- MCP server over stdio named `network-topology`, one tool `network-topology` with input schema: `site` (`production|dr|all`, default `all`), `time_range` (string, default `now-1h`), `focus_device` (optional string).
- Handler: run the Task-2 queries → `buildTopology` → return (a) a concise text summary (node count, edge count, cross-site edge count, unhealthy devices, warnings) AND (b) a `structuredContent` payload with the full `Topology` plus per-node link objects from Task 4.
- `focus_device` filters to that node's 1-hop neighborhood.
- Errors: auth/connection failures return a clear tool error naming the cause (distinct from "no data", which returns an empty topology + warnings).

**Verify:** handler tests (all-sites, filtered site, focus_device, empty-data, auth-error). Manual: `node dist/server.js` responds to an MCP `tools/list` handshake. Commit.

---

### Task 6: React map UI (MCP Apps resource)

**Files:** `ui/` (Vite React app), `src/ui-resource.ts` (serves the built HTML as an MCP UI resource), build wiring in `package.json`.

**Contract:**
- Force-directed graph, two visually separated clusters (production / DR) with cross-site edges styled distinctly (dashed + accent color); **uniform node sizes**; role conveyed by icon+color (firewall/router/switch/server/storage/database/ap/unknown); edge thickness ∝ bytes (log-scaled, clamped).
- Node health ring: ok/warn/crit/unknown colors. Legend + time-window label.
- Click a node → side panel: name, vendor, role, site, IP, health gauges, top talkers (from its edges), recent log volume, and the Kibana deep links from Task 4 as real anchors.
- The UI receives the topology payload from the tool result (MCP Apps data channel) — no direct ES access from the browser, no API key in the bundle (assert in a test that the built bundle contains no `ELASTIC_API_KEY`).
- Follows the repo's dataviz sensibilities: readable in light/dark, no reliance on color alone for role (icon + label).

**Verify:** `npm run build` produces the bundle; component tests for the panel and legend; the no-secret-in-bundle test. Commit.

---

### Task 7: Docs, CI, and live verification (controller-run)

**Files:** `mcp-app/README.md`, root `README.md` section, `.github/workflows/validate.yaml` (mcp-app job).

**Contract:**
- `mcp-app/README.md`: install, env setup, `npm run build`, and the exact `claude mcp add` command to register the server; a screenshot placeholder; note that it reads only ingested data.
- CI job: `npm ci`, `npm run typecheck`, `npm test`, `npm run build` in `mcp-app/`.

**Live verification (controller):** build, register the server, invoke the tool against the live project, and confirm — node count ≈ 20 SNMP devices (+ any unnamed NetFlow endpoints), ≈28 edges, both sites present, cross-site edges (VPN/replication/backup) visible, at least one Kibana deep link opens the expected filtered view. Human gate: the map renders and looks right.

---

## Verification checklist (plan-level)

- `npm test` + typecheck + build green in CI
- Tool returns a topology from live data with both sites and cross-site edges
- No `topology/network.yaml` import anywhere in `mcp-app/`
- No secret in the built UI bundle
- Map renders inline in Claude; side-panel deep links work
