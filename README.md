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

## Scenarios

The platform simulates 24 recurring failure and anomaly scenarios, 3 per telemetry source. Each fires every **3 hours ± up to 45 minutes** (seeded offset per scenario) for the duration shown. Backfilled history includes 7 days of prior firings.

| Scenario ID | Description | Duration |
|---|---|---|
| `panw.port_scan` | External port scan — dense THREAT/deny burst from fixed RFC 5737 IP | 10 min |
| `panw.malware_detect` | Malware detection burst — THREAT record rate increases ~60× | 30 min |
| `panw.vpn_flap` | VPN tunnel flap — SYSTEM events + NetFlow VPN bytes drop to ~1% | 20 min |
| `asa.brute_force` | AAA brute-force — burst of 113005 (auth rejected) from fixed attacker IP | 5 min |
| `asa.conn_storm` | Connection storm — 302013/302014/106023 flood from fixed IP, building linearly | 8 min |
| `asa.failover` | ASA HA failover — 104001 (secondary ACTIVE) then 104002 (primary recovers) | 25 min |
| `ios.intf_flap` | Interface flap — LINK-3-UPDOWN + LINEPROTO-5-UPDOWN alternating every 30 s | 6 min |
| `ios.stp_reconverge` | STP reconvergence — SPANTREE-2-TOPOLOGY_CHANGE + PORTSTATUS every 15 s | 5 min |
| `ios.cpu_spike` | CPU spike — SYS-3-CPUHOG with CPU% ramping 70→95% per second | 20 min |
| `meraki.ap_offline` | AP offline — events type=device_down then type=device_up | 15 min |
| `meraki.rogue_ap` | Rogue AP — Air Marshal type=air_marshal_detected, ssid=FreePublicWiFi | 12 min |
| `meraki.wan_failover` | WAN failover — type=uplink_change to wan2 then recovery to wan1 | 30 min |
| `mongo.slow_query_storm` | Slow query storm — extra COLLSCAN queries on unindexed `notes` field | 25 min |
| `mongo.repl_lag` | Replication lag — 20 bulk inserts/s drives measurable secondary lag | 30 min |
| `mongo.conn_exhaustion` | Connection exhaustion — 40 extra MongoClient connections held open | 25 min |
| `pg.deadlock` | Deadlock injection — advisory lock pair triggers `ERROR: deadlock detected` | 5 min |
| `pg.vacuum_load` | Vacuum load — dead tuple churn + VACUUM ANALYZE every 30 s for 60 min | 60 min |
| `pg.seqscan_regression` | Sequential scan regression — ILIKE queries on unindexed `notes` column | 20 min |
| `hpe.fan_failure` | HPE fan failure — iLO SNMP fan status degraded/failed | 30 min |
| `hpe.port_saturation` | HPE port saturation — Aruba switch uplink near 100% utilization | 25 min |
| `hpe.raid_degraded` | HPE RAID degraded — Alletra storage cpqDaLogDrvStatus = degraded | 30 min |
| `dell.psu_failure` | Dell PSU failure — iDRAC SNMP powerSupplyStatus = failed | 25 min |
| `dell.mem_leak` | Dell memory leak — hrStorageUsed rising monotonically over 60 min | 60 min |
| `dell.capacity_breach` | Dell capacity breach — storage hrStorageUsed/hrStorageSize ≥ 85% | 60 min |

For field-level detail on each scenario see `docs/scenarios/<source>.md`:
[panw](docs/scenarios/panw.md) · [asa](docs/scenarios/asa.md) · [ios](docs/scenarios/ios.md) · [meraki](docs/scenarios/meraki.md) · [mongodb](docs/scenarios/mongodb.md) · [postgresql](docs/scenarios/postgresql.md) · [hpe](docs/scenarios/hpe.md) · [dell](docs/scenarios/dell.md)

## Backfill

After deploying, populate 7 days of historical data so dashboards have data across their default time range:

```bash
make backfill
```

This runs `python -m synthsetup.backfill` which writes to all data streams (syslog, NetFlow, SNMP). It is **idempotent**: each run deletes the existing time-range data before re-writing, so re-running after a topology change or seed change is safe.

To populate only specific source types:

```bash
.venv/bin/python -m synthsetup.backfill --sources logs    # syslog sources only
.venv/bin/python -m synthsetup.backfill --sources metrics  # NetFlow + SNMP only
.venv/bin/python -m synthsetup.backfill --dry-run          # print volumes without writing
```

## Custom Dashboards

Three custom dashboards are bundled in `setup/dashboards/` and must be imported after deploy:

```bash
make import-dashboards
```

This runs `python -m synthsetup.import_dashboards` which POSTs each NDJSON file to the Kibana Saved Objects `_import` API with `overwrite=true`. The three dashboards:

| Dashboard ID | File | Purpose |
|---|---|---|
| `synthnet-hpe-infrastructure` | `setup/dashboards/hpe.ndjson` | HPE switch, server, and storage health (SNMP) |
| `synthnet-dell-infrastructure` | `setup/dashboards/dell.ndjson` | Dell switch, server, and storage health (SNMP) |
| `synthnet-network-overview` | `setup/dashboards/network-overview.ndjson` | Cross-source network overview (PANW, ASA, IOS, Meraki, NetFlow) |

## Network topology MCP app

[`mcp-app/`](mcp-app/README.md) ships a one-tool MCP server (`network-topology`) that renders an interactive prod/DR network map directly inside Claude Code. It queries only ingested Elasticsearch data — it never reads `topology/network.yaml`.

Live-verified result: **26 nodes / 28 edges / 6 cross-site edges** (18 production, 8 DR, zero warnings).

See [mcp-app/README.md](mcp-app/README.md) for setup, registration, and usage.
