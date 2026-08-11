# Plan 4: Backfill, Scenarios & Custom Dashboards — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Lean plan — each task states its contract and verification; implementers write tests to pin the contract.

**Goal:** Make the platform tell a story: 7 days of history on every spin-up, 24 recurring scenarios (3 per source) that fire every ~3h with seeded offsets, and custom HPE/Dell/Overview dashboards — closing out the original spec.

**Architecture:** A scenario engine in `synthgen.common.scenarios` that every source consults (pure, seeded, time-derived), so live emission and backfill produce identical events. A `synthsetup.backfill` job replays 7 days: logs are generated in wire format and bulk-indexed **through the real ingest pipelines**; metrics/NetFlow/SNMP history are synthesized as documents validated against the installed mappings first. Dashboards ship as committed NDJSON imported by a Kibana Saved Objects API job.

**Tech Stack:** unchanged (Python 3.12; the existing pure `generate_batch(topo, t, seed)` sources and `rate_multiplier` were designed for this reuse).

## Global Constraints

- **Determinism is the contract:** scenario schedule and all randomness derive from `(GLOBAL_SEED, key, time bucket)` with string-keyed PRNG. The same timestamp must produce the same events in backfill and in live emission — no wall-clock reads inside generators.
- Scenario cadence: each scenario fires every **3 hours ± a seeded offset up to 45 min**, staggered per source so firings spread across the day. Duration: minutes to ~1 hour depending on scenario.
- Backfill window: **7 days**, configurable via `--days`. Idempotent: re-running must not duplicate (use deterministic `_id` per synthetic doc where the API allows, and delete-by-query the backfill range first — pick one and document it).
- **Logs backfill must pass through the real ingest pipelines** (bulk index into the data stream; timestamps come from message content). Metrics/NetFlow/SNMP backfill is synthesized and MUST be validated against the installed index template before writing — hard-fail on unknown fields (this is the spec's stated safeguard).
- Every scenario gets a one-page doc in `docs/scenarios/<source>.md` (8 files, 3 scenarios each): what happens, which dashboards/fields show it, its schedule.
- Custom dashboards are committed NDJSON, imported idempotently; they must bind to fields that exist (verify against live mappings before finalizing panels).
- Existing green gates stay green: `python -m synthsetup.simulate` (wire formats), `make validate` (now including new checks), CI.

---

### Task 1: Scenario engine

**Files:** Create `src/synthgen/common/scenarios.py`; tests `tests/test_scenarios.py`.

**Contract:**
- `@dataclass(frozen=True) ScenarioSpec { id: str; source: str; every_s: int = 10800; jitter_s: int = 2700; duration_s: int; }`
- `SCENARIOS: dict[str, ScenarioSpec]` — the 24 ids (naming: `panw.port_scan`, `asa.brute_force`, …).
- `fires_at(spec, t, seed) -> bool` and `active_window(spec, t, seed) -> tuple[datetime, datetime] | None` — returns the current firing's window if `t` falls inside one.
- `phase(spec, t, seed) -> float | None` — 0.0→1.0 progress through the active firing (lets sources ramp effects).
- `active_scenarios(source, t, seed) -> list[tuple[ScenarioSpec, float]]` — everything currently firing for a source with its phase.
- Offsets are seeded per scenario id so the schedule is stable across processes and reproducible in backfill; staggering means two scenarios of the same source rarely overlap exactly (assert this in tests over a 7-day sweep).
- Pure; no module-level mutable state; no wall-clock.

**Verify:** determinism across processes (subprocess test like the pattern engine's); over a simulated 7 days each scenario fires ~56 times (8/day ±); windows never exceed duration; `phase` monotonic within a window. Commit.

---

### Task 2: Scenario effects in the syslog/NetFlow sources

**Files:** Modify `src/synthgen/syslog_gen/{asa_source,ios_source,panw_source,meraki_source}.py`, `src/synthgen/netflow_gen/source.py`; add scenario message builders to the relevant `formats/*.py`; tests per source.

**Contract — implement these (12 of the 24; DB/SNMP ones come in Tasks 3-4):**
- **Palo Alto:** `panw.port_scan` (burst of THREAT/deny from one external IP + matching NetFlow scan fan-out), `panw.malware_detect` (spyware/vulnerability THREAT verdicts + C2-ish flow), `panw.vpn_flap` (SYSTEM tunnel down/up + the site-vpn NetFlow flow drops to ~0 then resumes).
- **Cisco ASA:** `asa.brute_force` (113005 auth-failure burst from one IP), `asa.conn_storm` (302013/302014 storm + 106023 denies), `asa.failover` (failover syslogs).
- **Cisco IOS:** `ios.intf_flap` (LINK-3-UPDOWN + LINEPROTO pairs on one interface + NetFlow reroute), `ios.stp_reconverge` (STP syslogs + brief traffic dip), `ios.cpu_spike` (SYS mnemonics; SNMP CPU handled in Task 4).
- **Meraki:** `meraki.ap_offline` (device down/up syslog + webhook alert), `meraki.rogue_ap` (Air Marshal event), `meraki.wan_failover` (MX uplink change).
- Each source consults `active_scenarios(...)` inside its existing pure `generate_batch`, layering scenario events on top of baseline. Baseline behaviour when no scenario is active must be **byte-identical to today** (pin with a regression test at a known no-scenario timestamp).
- NetFlow effects: scenario-driven multipliers on specific flows (scan fan-out, vpn drop, reroute) computed from `active_scenarios('netflow', t, seed)` plus cross-source coupling (e.g. the vpn_flap spec id is read by both panw and netflow).

**Verify:** per-scenario tests asserting the marker messages appear inside the window and not outside; determinism; the no-scenario baseline regression test; **all new wire formats must pass `python -m synthsetup.simulate`** (extend its sample builders with one sample per new message type and bump pinned counts). Commit.

---

### Task 3: Database scenarios (real effects)

**Files:** Modify `src/synthgen/db_workload/{__init__,mongo,postgres}.py`; tests.

**Contract — 6 scenarios driven by REAL database work (no synthetic docs):**
- **MongoDB:** `mongo.slow_query_storm` (sustained unindexed `count_documents` collscans), `mongo.repl_lag` (write flood on primary → measurable replication lag), `mongo.conn_exhaustion` (open a burst of connections up to a safe cap, then release).
- **PostgreSQL:** `pg.deadlock` (two sessions acquiring locks in opposite order → real deadlock, caught and logged), `pg.vacuum_load` (explicit `VACUUM ANALYZE` + bulk churn in the backup window), `pg.seqscan_regression` (unindexed ILIKE scan mix elevating pg_stat_statements).
- All are bounded and safe: caps on connections/rows, timeouts, and full cleanup when the window ends; the workload loop must never crash-loop or exhaust the DB (retention from Plan 2 stays in force).
- Effects are visible in the existing `mongodb`/`postgresql` integration metrics — no new data streams.

**Verify:** unit tests for the query/query builders and the scenario gating (no live DB in unit tests); a documented manual check listing which metric each scenario moves. Commit.

---

### Task 4: SNMP scenarios (HPE/Dell/Cisco device health)

**Files:** Modify `snmp/generator/render.py`; add a scenario-aware responder path; tests.

**Contract — 6 scenarios:**
- **HPE:** `hpe.fan_failure` (fan status + temperature climb), `hpe.port_saturation` (ifUtilization near 100% + matching NetFlow elephant flow), `hpe.raid_degraded` (array health status change).
- **Dell:** `dell.psu_failure` (PSU status + power draw shift), `dell.mem_leak` (memory gauge sawtooth: climb ~3h then reset), `dell.capacity_breach` (capacity % crossing 85/90 then cleanup).
- **Design decision required (verify before building):** `.snmprec` files are static and snmpsim indexes them at startup. Determine the cheapest mechanism that makes scenario-driven values move: (a) a small sidecar/loop that re-renders the affected `.snmprec` files on the scenario schedule and triggers snmpsim to pick them up (verify snmpsim re-reads on mtime change; if it doesn't, restart or use its variation `writecache`), or (b) snmpsim's delegated/`sql`/`writecache` variation modules driven by an external value source. Prototype whichever is verifiable in ~30 minutes and document the choice and its evidence in the report.
- Scenario values must still be deterministic from `(t, seed)` so a backfill of SNMP history can reproduce the same curves.

**Verify:** renderer tests for scenario value curves; a real snmpsim run proving a scenario value CHANGES between two polls ~1 min apart (paste evidence — a real `snmpget`/`snmpwalk` diff, not a claim). Commit.

---

### Task 5: 7-day backfill

**Files:** Create `src/synthsetup/backfill.py`; modify `src/synthsetup/validate.py`; tests with respx.

**Contract:**
- `python -m synthsetup.backfill [--days 7] [--dry-run]`.
- **Logs** (`cisco_asa`, `cisco_ios`, `panw`, `cisco_meraki`): step the seeded clock across the window at the sources' natural tick, call the SAME pure `generate_batch` functions, and bulk-index the wire-format lines into each data stream so the real ingest pipeline parses them. Batch with error checks per batch; abort (don't skip) on pipeline errors.
- **NetFlow / SNMP / DB metrics**: synthesize documents matching the live mappings. Before writing, `validate_mappings()` must diff a sample synthesized doc against the installed index template and **hard-fail on unknown or missing required fields**.
- Rate control: cap concurrent bulk requests; log progress per simulated day.
- Idempotency: document and implement one strategy (deterministic doc `_id`, or delete-by-query over the backfill range for synthetic-only streams before writing).
- Seamlessness: the last backfilled tick and the first live tick must be continuous (same seeded schedule) — assert in a test that generating tick T via backfill equals generating tick T live.
- Add a validate check: history present (docs older than 24h exist in at least the log streams).

**Verify:** unit tests (bulk batching, mapping validation hard-fail, seam continuity); `--dry-run` prints planned volumes without writing. Commit.

---

### Task 6: Custom dashboards

**Files:** Create `setup/dashboards/{hpe,dell,network-overview}.ndjson`, `src/synthsetup/import_dashboards.py`; modify `deploy.sh`, `validate.py`, `k8s/jobs/`; tests.

**Contract:**
- **HPE Infrastructure**: server health (fans, temps, PSU), switch interface util/errors, storage array health/capacity — filterable by `device.name`.
- **Dell Infrastructure**: same structure for Dell devices.
- **Network Overview** (cross-source): total flows, top talkers, firewall denies, device health rollup, inter-site traffic, and a scenario-annotations panel.
- Panels must bind to fields verified present in live data (`metrics-snmp.device-*` uses `device.*` plus OID-named `snmp.*` keys — check exact key names before authoring; NetFlow/log fields per Plan 2).
- `import_dashboards.py`: Kibana Saved Objects `_import` with `overwrite=true`, idempotent, clear failure messages.
- `deploy.sh` runs it after fleet-setup; a K8s Job exists for parity; `make validate` gains a check that the three dashboards exist by id.

**Verify:** NDJSON parses and every referenced index pattern/data view is created or referenced correctly; import job idempotent on re-run (run twice). Commit.

---

### Task 7: Scenario docs + wiring + live E2E (controller-run)

**Files:** Create `docs/scenarios/{panw,asa,ios,meraki,mongodb,postgresql,hpe,dell}.md`; modify `README.md`, `docs/BACKLOG.md`.

**Contract:** each file documents its 3 scenarios: what happens, the data types touched, which dashboard/panel or query shows it, and the schedule. README gains a "Scenarios" section and a "Backfill" section (`make backfill`). Makefile gains `backfill`.

**Live verification (controller):** deploy; run backfill; confirm history appears; observe at least 3 different scenarios firing in live data within ~1 hour and verify each is visible in the intended dashboard/query; confirm the three custom dashboards render; `make validate` all green; then a full `make down && make up && make backfill` reproducibility cycle. Human gate: dashboards + scenario stories look right.

---

## Verification checklist (plan-level)

- All 24 scenarios implemented, documented, and observed firing on schedule
- Backfill produces 7 days of history that is continuous with live data at the seam
- Mapping validation hard-fails on bad synthetic docs (proven by a test)
- Three custom dashboards imported idempotently and populated
- `make validate` green including new history/dashboard checks; CI green
- Full teardown → up → backfill cycle reproduces everything
