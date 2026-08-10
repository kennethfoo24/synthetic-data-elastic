# Plan 2: All Data Sources — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement task-by-task. Deliberately leaner than Plan 1: each task states its contract and verification; implementers write the tests to pin the contract (TDD), following the conventions Plan 1 established.

**Goal:** Light up every remaining data source — Cisco IOS, Palo Alto, NetFlow, SNMP (HPE/Dell/Cisco), MongoDB, PostgreSQL, Meraki — flowing through the Fleet-managed agent into their integrations with pre-built dashboards.

**Architecture:** Extends Plan 1's proven pattern: pure `generate_batch(topo, t, seed)`-style sources per vendor, one multi-mode image, integration policies added in `fleet_setup.py`, one validate check per data stream. New: real MongoDB/Postgres StatefulSets (agent scrapes them), snmpsim serving 18 SNMP endpoints, FastAPI Meraki mock, and a minimal NetFlow v9 encoder driven by the topology flow matrix.

**Tech Stack:** unchanged (Python 3.12, httpx/respx, pydantic; FastAPI+uvicorn and snmpsim added as deps). Conventions carried from Plan 1 (binding): string-keyed PRNG seeding `f"{seed}|{key}|{bucket}"`; pure batch generators (no I/O); wire formats verified against the REAL ingest pipeline via `_ingest/pipeline/_simulate` BEFORE deploy (the ASA zero-pad lesson); integration input/var names verified live via `GET /api/fleet/epm/packages/<pkg>` (the udp_host lesson); images referenced by git-SHA tag at deploy time.

## Global Constraints

- Agent input ports: ASA 9001 (exists), **IOS 9002**, **PANW 9003**, **NetFlow 2055** — all UDP, exposed on the `elastic-agent` Service.
- Integrations: `cisco_ios`, `panw`, `netflow`, `snmp`, `mongodb`, `postgresql`, `cisco_meraki` — one `ensure_package_policy` call each in `fleet_setup.py`; latest package versions.
- Every source's emission rate flows through `rate_multiplier` from `synthgen.common.patterns`; NetFlow byte counts derive from `topology/network.yaml` flow matrix `baseline_bps` (flows are the single source of truth for inter-device traffic — finding #9 from Plan 1's final review).
- Every new data stream gets a check in `synthsetup/validate.py` `CHECKS`.
- K8s namespace `synthetic-network`; all new images are the same `kennethfoo24/synthetic-netgen` multi-mode image except snmpsim data (baked into same image) and databases (upstream `mongo:7` / `postgres:16` images).
- BACKLOG.md entry work is Task 1 — it gates everything (policy updates must reconcile, deploys must not race CI).
- MCP app moved up: it becomes Plan 3 (user priority); backfill/scenarios/custom dashboards become Plan 4.

---

### Task 1: Hardening entry work (from BACKLOG.md)

**Files:** Modify `src/synthsetup/fleet_client.py`, `deploy.sh`; test `tests/test_fleet_client.py`.

**Contract:**
- `ensure_package_policy` on HTTP 409: look up the existing policy id by name (`GET /api/fleet/package_policies?kuery=name:"<name>"`), then `PUT /api/fleet/package_policies/<id>` with the same body — so config changes reconcile on re-run. Tests: 409→lookup→PUT path with respx; PUT failure raises `FleetSetupError`.
- `deploy.sh`: after computing `IMAGE_TAG`, fail fast with a clear message if (a) working tree is dirty (`git status --porcelain` non-empty) or (b) `docker manifest inspect kennethfoo24/synthetic-netgen:$IMAGE_TAG` fails (image not on Docker Hub yet — tell the user to wait for CI).

**Verify:** full suite green; `bash -n deploy.sh`; manual `docker manifest inspect` of current HEAD tag succeeds. Commit.

---

### Task 2: Cisco IOS syslog source

**Files:** Create `src/synthgen/syslog_gen/formats/ios.py`, `src/synthgen/syslog_gen/ios_source.py`; modify `src/synthgen/__main__.py` (mode `syslog-ios`), `src/synthsetup/fleet_setup.py` (cisco_ios policy, UDP 9002), `src/synthsetup/validate.py`, `k8s/elastic-agent.yaml` (port 9002), `k8s/generators/syslog-gen.yaml` → add a second container or Deployment `syslog-ios-gen`; tests for formats + source.

**Contract:**
- Wire format (facility local7): `<189>{seq}: {hostname}: {ts_ios}: %{FACILITY}-{SEV}-{MNEMONIC}: {body}` where `ts_ios` = `Aug 11 2026 12:34:56.789` (millis) and `seq` is a per-device monotonically increasing message counter. Message types for baseline: `%SYS-5-CONFIG_I` (config), `%LINK-3-UPDOWN` + `%LINEPROTO-5-UPDOWN` (interface flaps, rare at baseline), `%SEC_LOGIN-5-LOGIN_SUCCESS`, `%SYS-6-LOGGINGHOST_STARTSTOP`.
- All `vendor_os: ios` devices (6) emit, interleaved, rates via `rate_multiplier(t, "user", f"ios:{name}")` scaled to ~2 msg/s/device peak.
- `generate_batch(topo, t, seed)` pure, same signature convention as ASA.
- **MANDATORY before integration policy lands in fleet_setup:** verify `cisco_ios` input/stream/var names via `GET /api/fleet/epm/packages/cisco_ios` (script it like Plan 1's preflight; likely `cisco_ios-udp` / `cisco_ios.log` / `udp_host`+`udp_port` but VERIFY) and validate one sample of each message type via `POST /_ingest/pipeline/logs-cisco_ios.log-<ver>/_simulate` — all must parse with `event.code`/mnemonic extracted, no `error.message`.
- Validate check: `logs-cisco_ios.log-default` docs in last 5m.

---

### Task 3: Palo Alto PAN-OS source

**Files:** Create `src/synthgen/syslog_gen/formats/panw.py`, `src/synthgen/syslog_gen/panw_source.py`; modify `__main__.py` (mode `syslog-panw`), `fleet_setup.py` (panw policy, UDP 9003), `validate.py`, k8s (port 9003, Deployment `syslog-panw-gen`); tests.

**Contract:**
- PAN-OS syslog carries a CSV body: `<14>{ts_rfc3164} {hostname} {csv}` where csv starts `1,{receive_time},{serial},{TYPE},{subtype},...` — TYPE ∈ TRAFFIC (subtype end/start), THREAT (subtype spyware/vulnerability), SYSTEM. **The panw pipeline requires exact field counts per type** — do NOT guess: pull the field order from the integration's docs/pipeline and pin each rendered CSV against `_simulate` (every sample must yield `panw.panos.*` fields, no error). This simulate check is a committed pytest-marked live test AND a preflight script step.
- Only `palo-fw-prod` emits. TRAFFIC records derive src/dst/bytes from topology flows crossing the firewall (site egress + inter-site VPN flow); THREAT records rare at baseline (~1/min); SYSTEM sparse.
- Validate checks: `logs-panw.panos_traffic-default` (and threat stream) docs in last 5m.

---

### Task 4: NetFlow generator

**Files:** Create `src/synthgen/netflow_gen/encoder.py` (minimal NetFlow v9), `src/synthgen/netflow_gen/source.py`; modify `__main__.py` (mode `netflow`), `fleet_setup.py` (netflow policy, UDP 2055), `validate.py`, k8s (port 2055, Deployment `netflow-gen`); tests.

**Contract:**
- Minimal v9 encoder: header (version=9, count, sysUptime, unixSecs, seq, sourceId) + template flowset (id 0) declaring fields `IPV4_SRC_ADDR(8), IPV4_DST_ADDR(12), L4_SRC_PORT(7), L4_DST_PORT(11), PROTOCOL(4), IN_BYTES(1,4), IN_PKTS(2,4), FIRST_SWITCHED(22), LAST_SWITCHED(21)` + data flowsets. Re-send template every N packets (agent decoder needs it before data). Unit-test by decoding own bytes with struct (round-trip).
- `source.py` walks `topo.flows` each tick: bytes = `baseline_bps × rate_multiplier(t, flow_class, flow.name) / 8` per interval, plus reverse-direction response flow (~10% of bytes); backup flows only emit meaningfully inside `in_backup_window` (use the overlay: multiply by 20× in window, 0.05× outside). Src port deterministic-random per flow+bucket.
- Exporter identity: one exporter (the generator pod) is acceptable for Plan 2; per-device exporters deferred to the MCP-app plan if the map needs them (record decision in code comment — the map draws edges from src/dst IPs, which are correct regardless).
- Validate check: `logs-netflow.log-default` docs in last 5m AND an ES terms agg over `source.ip`×`destination.ip` returning ≥ 10 distinct pairs (proves the flow matrix is represented — this is the query the MCP app will build on).

---

### Task 5: SNMP — snmpsim + generic SNMP integration

**Files:** Create `snmp/generator/render.py` (renders `.snmprec` per device from topology), `snmp/data/` (committed rendered output), `k8s/generators/snmpsim.yaml`; modify `Dockerfile` (install snmpsim, copy snmp/), `fleet_setup.py`, `validate.py`; tests for the renderer.

**Contract:**
- All non-database, non-meraki devices get SNMP profiles (18 devices): sysDescr/sysName/sysObjectID per vendor (HPE Aruba/iLO, Dell OS10/iDRAC/PowerStore, Cisco IOS/ASA strings), ifTable (2-8 interfaces with counters), CPU/memory gauges (vendor MIB OIDs where practical, else HOST-RESOURCES), plus for storage devices capacity OIDs. `sysName` MUST equal the topology device name (the MCP app resolves node identity from it).
- snmpsim serves all devices from ONE pod, port 161/udp, **community string = device name** (snmpsim's community-based data-file selection); Service `snmpsim`.
- Fleet: verify the `snmp` package's policy shape live (hosts/community/oids vars), then one package policy per vendor group or per device — whichever the package supports; poll interval 60s, targeting `snmpsim` service DNS with each device's community.
- Gauges vary over time: snmpsim's `numeric` variation module (or pre-rendered time-series via the writecache module) — implementer picks the simplest snmpsim-native mechanism that makes CPU/mem/traffic counters move between polls; document choice.
- Validate check: `metrics-snmp.*` docs in last 5m and ≥ 18 distinct hosts.

---

### Task 6: MongoDB + PostgreSQL (real instances + workload)

**Files:** Create `k8s/databases/mongodb.yaml` (prod StatefulSet + dr as replica-set secondary), `k8s/databases/postgres.yaml` (prod + streaming standby), `src/synthgen/db_workload/{mongo.py,postgres.py}`; modify `__main__.py` (mode `db-workload`), `fleet_setup.py` (mongodb + postgresql policies), `validate.py`, `pyproject.toml` (pymongo, psycopg deps); tests (workload query builders only — no live DB in unit tests).

**Contract:**
- MongoDB: 2-member replica set (`mongodb-prod` primary, `mongodb-dr` secondary) via StatefulSets + headless Services; keyfile auth or authless in-namespace (simplest; document). PG: primary + hot standby with streaming replication (official image + `pg_basebackup` init container).
- `db-workload` mode runs continuous CRUD against both: an `orders`-style collection/table, rate via `rate_multiplier(t, "app", ...)`; includes a slow unindexed query every ~5 min (fodder for slow-query panels; full scenarios come in Plan 4).
- Fleet: verify `mongodb` and `postgresql` package policy shapes live; hosts point at the in-cluster Services; PG integration needs `pg_stat_statements` (enable via `shared_preload_libraries` in the manifest) and log collection via the container logfile path — if container-log collection is impractical with a single non-DaemonSet agent, scope Plan 2 to METRICS ONLY and record logs as a known gap for the K8s-integration follow-up (decide against the live package policy shape, not by guessing).
- Validate checks: `metrics-mongodb.status-default` and `metrics-postgresql.database-default` (exact stream names verified live) docs in last 5m.

---

### Task 7: Meraki mock + integration

**Files:** Create `src/synthgen/meraki_mock/app.py` (FastAPI), `src/synthgen/syslog_gen/formats/meraki.py` + `meraki_source.py`, `k8s/generators/meraki-mock.yaml`; modify `__main__.py` (mode `meraki-mock` runs uvicorn; mode `syslog-meraki`), `fleet_setup.py`, `validate.py`; tests (FastAPI TestClient).

**Contract:**
- First verify live how `cisco_meraki` ingests (`GET /api/fleet/epm/packages/cisco_meraki`): which inputs exist (syslog vs API polling), whether the API poller's base URL is overridable. **If the API base URL is NOT overridable, ship syslog-only and record the API-polling gap in BACKLOG.md** — do not build a mock nobody can point the agent at.
- Syslog: Meraki format lines (`flows`, `urls`, `events` from MX/AP device names in topology) to the port the integration expects (add to agent Service).
- Mock API (if usable): minimal endpoints the integration polls (organizations, networks, devices, device statuses) returning topology-derived JSON; API key auth accepting a configured token.
- Validate check: whichever `logs-cisco_meraki.*` stream applies.

---

### Task 8: Deploy integration + live E2E (controller-heavy)

**Files:** Modify `deploy.sh` (apply new manifests, SHA-pin every synthetic-netgen reference — generalize the sed to all generator manifests), `README.md` (Quick start now real; remove stale line; document `.venv` bootstrap + `make bootstrap` target in Makefile); `k8s/kustomization.yaml` — either add all new resources AND make CI's kustomize check meaningful, or delete it and drop the CI step (pick one; BACKLOG item #7).

**Verification (live, in order):**
1. `make test` + CI green; image for HEAD on Docker Hub
2. `make down && make up` from scratch — ALL policies created, all pods Ready
3. `make validate` — every check green (now ~10 checks)
4. Human gate: [Cisco] ASA + IOS + PANW dashboards, NetFlow overview, SNMP metrics in Discover, MongoDB + PostgreSQL dashboards all populating
5. Second `make down && make up` — reproducibility with reconcile path exercised

---

## Verification checklist (plan-level)

- All 7 sources flowing simultaneously; `make validate` all green; both dashboard sets populating (human-confirmed)
- Full teardown/redeploy cycle twice
- Every wire format pinned by a pipeline `_simulate` test/script (no repeat of the ASA teardown silent-drop)
- Flow matrix consumed by NetFlow gen (and PANW traffic logs) — topology single-source-of-truth restored
