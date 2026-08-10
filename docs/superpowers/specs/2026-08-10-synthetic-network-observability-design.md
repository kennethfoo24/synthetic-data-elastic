# Synthetic Network Observability Platform — Design

**Date:** 2026-08-10
**Status:** Approved (pending final spec review)
**Owner:** kenneth.foo@elastic.co

## Purpose

A reproducible synthetic data platform that continuously generates network/infrastructure telemetry (logs, metrics, SNMP, NetFlow) into an Elastic Serverless Observability project, mapped to official Elastic integrations so their pre-built dashboards populate. Plus a standalone MCP app that renders an interactive network topology map from the ingested data.

**Reproducibility requirement:** when the serverless project is destroyed and recreated, one command re-establishes everything — integrations, dashboards, 7 days of history, and continuous generation — within ~10–15 minutes.

## Decisions Log

| # | Decision | Choice |
|---|----------|--------|
| 1 | Runtime | Containers on user's existing Kubernetes cluster |
| 2 | Ingest path | Fleet-managed Elastic Agent (single enrolled Agent pod) |
| 3 | Setup automation | Fleet API + Kibana API via idempotent K8s Jobs (no Terraform) |
| 4 | HPE/Dell | Generic SNMP integration + custom importable dashboards |
| 5 | Data realism | Realistic diurnal/weekly patterns + 3 scenarios per source, firing every ~3h with seeded random offsets |
| 6 | Topology | ~26 devices across a Production site and a DR site, connected by VPN/replication/backup flows |
| 7 | History | 7-day backfill + continuous emission, seamless at the seam |
| 8 | Visualization | Standalone minimal MCP app (TypeScript) with one `network-topology` tool |
| 9 | CI/CD | GitHub Actions in `github.com/kennethfoo24/synthetic-data-elastic`, pushing images to Docker Hub `kennethfoo24/*` |
| 10 | Stack | Python (generators, jobs), TypeScript/React (MCP app) |

## Integration Coverage

| Source | Elastic Integration | Data types | Dashboards |
|--------|--------------------|-----------|------------|
| Palo Alto NGFW | `panw` | Traffic/threat/system logs (syslog, PAN-OS CSV) | Pre-built |
| Cisco ASA | `cisco_asa` | Syslog (conn, auth, threat, failover) | Pre-built |
| Cisco IOS routers/switches | `cisco_ios` | Syslog | Pre-built |
| Cisco Meraki | `cisco_meraki` | Syslog + cloud API polling (mocked) | Pre-built |
| MongoDB (prod + DR replica) | `mongodb` | Real metrics, logs, slow queries from live instances | Pre-built |
| PostgreSQL (prod + DR standby) | `postgresql` | Real metrics, logs, pg_stat_statements | Pre-built |
| HPE (servers, switches, storage) | `snmp` (generic) | SNMP metrics via snmpsim | **Custom** (importable NDJSON) |
| Dell (servers, switches, storage) | `snmp` (generic) | SNMP metrics via snmpsim | **Custom** (importable NDJSON) |
| All network devices | `netflow` | NetFlow v9 flows between devices | Pre-built |

**Fidelity caveats (accepted):**

1. `cisco_asa` / `cisco_ios` / `panw` are log integrations; device health metrics (CPU/mem/interfaces) for those devices come via the generic SNMP integration. Their pre-built dashboards are log-driven and fully populate.
2. Live data maps to integrations **by construction** (real Agent inputs, real ingest pipelines, real DB instances). Backfilled **logs** also go through the real pipelines. Backfilled **metrics/SNMP/NetFlow history** are synthesized documents validated against the installed index mappings before writing (hard-fail on mismatch).

## Architecture

```
┌─────────────────── Kubernetes cluster ───────────────────────┐
│  namespace: synthetic-network                                │
│                                                              │
│  Generators (Deployments)          Elastic Agent             │
│    syslog-gen  ──UDP──────────────▶ (Fleet-managed pod)      │
│    netflow-gen ──UDP──────────────▶   syslog inputs          │
│    snmpsim     ◀──SNMP polls──────    netflow input          │
│    meraki-mock ◀──API polls───────    snmp + meraki inputs   │
│                                       mongodb/postgresql     │
│  Real workloads (scraped)             inputs                 │
│    mongodb-prod / mongodb-dr  ◀───         │                 │
│    postgres-prod / postgres-dr ◀──         ▼                 │
│    db-workload-gen                  Elastic Serverless       │
│                                     Observability project    │
│  Run-once Jobs (per spin-up)               ▲                 │
│    fleet-setup → import-dashboards ────────┘                 │
│    → backfill → validate                                     │
└──────────────────────────────────────────────────────────────┘

Workstation:  mcp-app/ → `network-topology` MCP tool (ES|QL queries + React map)
```

**Shared topology model:** `topology/network.yaml` is the single source of truth — every device (`name, vendor, model, role, site, ip, snmp_profile, links[]`) plus a **flow matrix** (src device, dst device, ports, baseline rate, flow class: user/replication/vpn/backup). All generators, the backfill job, and validation derive from it. The MCP app deliberately does **not** read it — it discovers topology from ingested data, doubling as an end-to-end test.

## Network Topology (~26 devices)

```
PRODUCTION (10.10.0.0/16)              DR (10.20.0.0/16)
├─ palo-fw-prod (Palo Alto NGFW edge)  ├─ cisco-asa-dr (edge firewall)
├─ cisco-rtr-core-01/02 (IOS routers)  ├─ cisco-rtr-dr (IOS router)
├─ cisco-sw-access-01..03 (IOS sw)     ├─ cisco-sw-dr-01 (IOS switch)
├─ meraki-ap-01..02 + meraki-mx-01     ├─ dell-sw-dr (Dell switch)
├─ hpe-sw-01, dell-sw-01               ├─ hpe-srv-dr-01 (HPE server)
├─ hpe-srv-01/02, dell-srv-01/02       ├─ mongodb-dr (replica)
├─ hpe-storage-01, dell-storage-01     └─ postgres-dr (standby)
├─ mongodb-prod, postgres-prod

INTER-SITE FLOWS
├─ Site-to-site VPN (palo-fw-prod ↔ cisco-asa-dr)
├─ DB replication (mongodb-prod → mongodb-dr, postgres-prod → postgres-dr)
└─ Nightly backups (prod servers/storage → DR storage, 01:00–03:00)
```

Intra-site traffic follows realistic hops (server → access switch → core router → firewall). NetFlow records carry correct src/dst IPs/ports/bytes so the flow graph reconstructs this topology.

## Repository Layout

```
synthetic-data-elastic/
├── .github/workflows/
│   ├── build-push.yaml         # main: build+push multi-arch images to Docker Hub
│   └── validate.yaml           # PR: lint, unit tests, kustomize dry-run
├── topology/network.yaml       # shared model: devices, IPs, sites, links, flow matrix
├── generators/                 # Python; ONE image, mode flag per Deployment
│   ├── syslog_gen/{formats/,scenarios/}   # ASA, IOS, PANW, Meraki wire formats
│   ├── netflow_gen/            # NetFlow v9 sender driven by flow matrix
│   ├── meraki_mock/            # FastAPI fake Meraki cloud API
│   ├── db_workload/            # MongoDB + Postgres query generators
│   └── common/                 # topology loader, pattern engine, seeded clock
├── snmp/
│   ├── data/                   # snmpsim .snmprec files per device
│   └── generator/              # renders .snmprec from topology + patterns
├── setup/
│   ├── fleet_setup.py          # Fleet API: policy, integrations, enroll token
│   ├── dashboards/*.ndjson     # custom HPE, Dell, Network Overview dashboards
│   ├── import_dashboards.py    # Kibana Saved Objects API
│   ├── backfill.py             # 7-day history bulk-writer
│   └── validate.py             # mappings diff, data-stream/doc checks, agent health
├── k8s/                        # manifests + kustomize
│   ├── elastic-agent.yaml, generators/, databases/, jobs/, secrets.example.yaml
├── mcp-app/                    # standalone TypeScript MCP app
│   ├── server/{queries/}       # MCP server, ES|QL queries
│   └── ui/                     # React force-graph map
├── docs/scenarios/             # 8 files, 3 scenarios each
├── deploy.sh                   # the one command
└── Makefile                    # up / down / backfill / validate
```

**Images on Docker Hub:** `kennethfoo24/synthetic-netgen` (multi-mode generator), `kennethfoo24/synthetic-snmpsim`, `kennethfoo24/synthetic-meraki-mock`. Multi-arch (amd64/arm64), tagged `:latest` + `:sha`. Repo secrets: `DOCKERHUB_USERNAME`, `DOCKERHUB_TOKEN`. The MCP app is CI-tested but not containerized (runs on workstation via MCP host).

## Data Generation

### Pattern engine (shared by live generators and backfill)

`value = baseline × diurnal(t) × weekly(t) × jitter`

- **diurnal:** ramp 07:00, peak 10:00–16:00, trough 02:00 (timezone-configurable)
- **weekly:** weekend dip to ~30% for user traffic; flat for infrastructure noise
- **overlays:** nightly backup window 01:00–03:00 (DB load + prod→DR flows spike); Sunday 04:00 maintenance
- **jitter:** bounded random walk (organic-looking lines)
- **Seeded PRNG + schedule:** backfill and live generation compute identical values for identical timestamps → no visible seam.

### Scenarios

Each scenario fires **every ~3 hours with a seeded random offset (±45 min)**, staggered per source. Each spans minutes to ~1 hour and touches multiple data types for cross-dashboard corroboration. Each has a one-page doc in `docs/scenarios/`: what happens, which dashboards/fields show it, its schedule.

| Source | Scenarios (3 each) |
|--------|--------------------|
| **Palo Alto** | Port-scan blocked (threat logs + NetFlow scan pattern) · Malware/spyware detection (threat+traffic logs + C2 flow) · VPN tunnel flap to DR (system logs + inter-site flows stop/resume + SNMP ifstate) |
| **Cisco ASA** | Brute-force VPN logins (113005 + lockout) · Connection-limit storm (302013/14 + 733100) · Failover to standby (failover syslogs + SNMP blip) |
| **Cisco IOS** | Interface flap on core router (LINK-3-UPDOWN + SNMP errors + NetFlow reroute) · STP reconvergence (syslogs + traffic dip) · CPU spike (SNMP CPU + syslog) |
| **Meraki** | AP offline/online (API status + syslog + client drop) · Rogue AP detected (Air Marshal + syslog) · MX WAN uplink failover (API + syslog) |
| **MongoDB** | Slow-query storm — real unindexed scans (profiler logs + latency metrics) · Replication lag (lag metric + replication flow swells) · Connection-pool exhaustion (conn metric + warnings) |
| **PostgreSQL** | Real deadlock (deadlock logs + lock metrics) · Vacuum/backup load in backup window (I/O metrics + logs + DR flow) · Seq-scan regression (pg_stat_statements hot query) |
| **HPE** | Fan failure → thermal climb (SNMP) · Switch port saturation (SNMP util + NetFlow elephant flow) · Storage RAID degraded (SNMP health) |
| **Dell** | PSU failure, redundancy lost (SNMP) · Memory-leak sawtooth: climb ~3h, "reboot", repeat (SNMP) · Storage capacity fill-then-cleanup crossing 85/90% each cycle (SNMP) |

### Emission mechanics

- **syslog-gen:** one Deployment emitting interleaved wire-format streams for all syslog devices to the Agent's UDP inputs (one port per integration). Message content carries device identity (hostname, observer fields per format).
- **netflow-gen:** walks the flow matrix each interval; emits NetFlow v9 packets with pattern-engine-scaled byte/packet counts.
- **snmpsim:** one pod serving ~26 simulated SNMP endpoints (community/port per device); `.snmprec` files rendered from topology with time-varying counters; Agent SNMP integration polls each.
- **meraki-mock:** FastAPI server mimicking the Meraki cloud API endpoints the `cisco_meraki` integration polls (API URL overridden in integration policy); plus Meraki-format syslog.
- **Databases:** real MongoDB (prod + DR replica set member) and PostgreSQL (prod + streaming standby) StatefulSets; `db_workload` runs real queries — including deliberately slow/deadlocking ones on scenario schedule — so all DB telemetry is genuine.

## Reproducibility Flow

`./deploy.sh` (or `make up`) — inputs: ES URL, Kibana URL, API key (from `.env`, gitignored → K8s Secret `elastic-credentials`).

1. **fleet-setup Job** (Fleet API): create agent policy `synthetic-network`; add all integration policies with input config (UDP ports, snmpsim hosts, DB conn strings, Meraki mock URL). Package installation auto-installs dashboards, ingest pipelines, index templates. Generate enrollment token → K8s Secret.
2. **elastic-agent** Deployment enrolls and starts inputs.
3. **import-dashboards Job** (Kibana Saved Objects API): import custom NDJSON — HPE dashboard, Dell dashboard, Network Overview dashboard.
4. **backfill Job:** 7 days of history. Logs = wire-format messages bulk-indexed through the real ingest pipelines (timestamps from message content). Metrics/SNMP/NetFlow = synthesized docs; `validate.py` diffs against installed mappings first, hard-fails on mismatch. Same seed/schedule as live → seamless.
5. **Generators** start; seeded clock picks up where backfill ended.
6. **validate Job:** every expected data stream has docs in last 5 min; saved objects present; agent healthy in Fleet; topology ES|QL sanity check (~26 nodes, expected edge count). Green/red report.

All Jobs are idempotent — safe to re-run against a half-configured project. `make down` deletes the namespace; nothing stateful lives outside the cluster + Git repo.

## MCP App: `network-topology`

Standalone TypeScript MCP app (structure referenced from `elastic/example-mcp-app-observability`; no fork). One tool.

- **Inputs:** `site` (`production`|`dr`|`all`, default `all`), `time_range` (default 1h), optional `focus_device`.
- **Config:** `.env` with ES URL, Kibana URL, API key.
- **Edges:** ES|QL over `logs-netflow.log-*` grouped by `source.ip`/`destination.ip` (sum bytes/packets, top ports). Edges crossing `10.10/16 ↔ 10.20/16` classified inter-site (VPN/replication/backup), drawn dashed/colored.
- **Nodes:** identity from SNMP `sysName`/`sysDescr` + syslog `observer.*`/`host.name` — discovered from data, never from `network.yaml`.
- **Health overlay:** latest SNMP CPU/memory/interface status → node color (green/amber/red); scenario effects visible on the map.
- **UI:** React force-directed graph, two visually separated site clusters bridged by inter-site edges. **Uniform node sizes**; role conveyed by icon (firewall/router/switch/server/storage/db). Edge thickness = bytes. Legend + time-range indicator. Re-invocable with different params conversationally.
- **Side panel (on node click):** device details, health gauges, top talkers, recent log volume, **plus deep links into the Elastic UI**: Discover pre-filtered to the device (`observer.name`/`host.name`, current time range), the relevant integration dashboard, and for HPE/Dell the custom dashboard filtered to that device.
- **Non-goals (YAGNI):** no alerting, no editing, no live streaming, no multi-cluster config.

## Custom Dashboards (importable NDJSON)

1. **HPE Infrastructure** — server health (fans, temps, PSU), switch interface util/errors, storage array health/capacity; filterable by device.
2. **Dell Infrastructure** — same structure for Dell devices.
3. **Network Overview** — cross-source: total flows, top talkers, firewall denies, device health rollup, inter-site traffic.

Built against the generic SNMP integration's field schema (+ NetFlow/log fields for the overview). Version-controlled as NDJSON; imported by Job on every spin-up.

## Testing & Validation

- **Unit (CI, on PR):** wire-format templates parse against known-good samples; pattern engine determinism (same seed+t → same value); topology YAML schema validation; flow-matrix referential integrity.
- **Mapping validation (deploy-time):** synthesized backfill docs diffed against installed index templates; hard-fail on unknown fields.
- **End-to-end (deploy-time `validate` Job):** data-stream doc counts, saved-object presence, agent health, topology node/edge counts via the same ES|QL the MCP app uses.
- **MCP app (CI):** query-builder unit tests; UI component render tests.

## Error Handling Principles

- Setup Jobs: idempotent, explicit failure messages naming the API call and response; no partial-success silence.
- Generators: if the Agent input is unreachable, retry with backoff and log loudly; never crash-loop silently.
- Backfill: batched bulk writes with per-batch error checks; abort (don't skip) on mapping validation failure.
- MCP app: distinguish "no data" (empty map + guidance to run validate) from query/auth errors.

## Milestone Order (for planning)

1. Repo + CI skeleton, topology model, pattern engine
2. Fleet setup Job + Elastic Agent deployment (one integration end-to-end: Cisco ASA)
3. Remaining syslog sources (IOS, PANW), NetFlow generator
4. SNMP (snmpsim + profiles), databases + workload, Meraki mock
5. Backfill + validation
6. Custom dashboards
7. Scenarios (engine + all 24 + docs)
8. MCP app
