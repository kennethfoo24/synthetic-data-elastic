# PostgreSQL Scenarios

Data stream: `metrics-postgresql.activity-default`
Source: `postgres-prod` (primary, `10.10.7.21`) via DSN `postgresql://synth:devpass123@postgres-prod:5432/synthdb`

The PostgreSQL workload generator connects to the live PostgreSQL instance. All three scenarios drive real database activity visible in the Elastic `postgresql` metrics integration.

---

## pg.deadlock — Deadlock pair injection

**Schedule:** Every 3h ± up to 45 min. Duration: ~5 minutes (300 s).

**What happens:** During the window, the workload generator opens two concurrent PostgreSQL sessions that acquire advisory locks in opposite order (`pg_advisory_xact_lock(1001)` then `1002` vs. `1002` then `1001`). PostgreSQL's deadlock detector (default 1 s timeout) fires, aborts one session with `ERROR: deadlock detected`, and both connections are rolled back. One deadlock pair is triggered every 30 seconds within the window, producing approximately 10 deadlock events over the 5-minute duration.

**Data touched:**
- Data stream: `metrics-postgresql.activity-default`
- `postgresql.activity.state`: `"idle in transaction (aborted)"` — appears for the aborted session immediately after the deadlock is detected; baseline sessions are `"active"` or `"idle"`
- `postgresql.activity.waiting`: `true` — one of the two sessions is waiting on the lock the other holds during the circular-wait phase (≤ 1 second)
- `postgresql.activity.query`: `"SELECT pg_advisory_xact_lock(1001)"` or `"SELECT pg_advisory_xact_lock(1002)"` — these advisory lock queries never appear in baseline activity

**Where to see it:**
- Dashboard: `synthnet-network-overview` — PostgreSQL activity panel; filter `postgresql.activity.state: "idle in transaction (aborted)"`; pattern is burst of 2 aborted sessions every 30 seconds
- ES query: `GET /metrics-postgresql.activity-default/_search?q=postgresql.activity.state:"idle in transaction (aborted)"&size=10`

**Scenario markers** (fields/values that confirm it's active):
- `postgresql.activity.state: "idle in transaction (aborted)"` — only produced by the deadlock scenario; baseline has zero aborted-transaction states
- `postgresql.activity.query` containing `"pg_advisory_xact_lock"` — this SQL never appears in baseline activity

---

## pg.vacuum_load — Autovacuum pressure (dead tuple churn)

**Schedule:** Every 3h ± up to 45 min. Duration: ~60 minutes (3600 s).

**What happens:** The workload generator bulk-inserts rows into the `orders` table and immediately deletes them every second, creating a continuous stream of dead tuples. Additionally, `VACUUM ANALYZE orders` is run every 30 seconds to force autovacuum work and checkpoint I/O. Over the 60-minute window, this creates sustained bloat-and-cleanup pressure that manifests in PostgreSQL's bgwriter and autovacuum statistics.

**Data touched:**
- Data stream: `metrics-postgresql.activity-default`
- `postgresql.stat.bgwriter.buffers_clean`: increases as the bgwriter is forced to write dirty pages more frequently during VACUUM
- `postgresql.stat.bgwriter.maxwritten_clean`: spikes when the bgwriter hits its max_pages_per_flush limit under vacuum I/O pressure
- `postgresql.stat.table.n_dead_tup` (on the `orders` table): accumulates between VACUUM runs; drops sharply every 30 seconds when VACUUM reclaims dead tuples
- SQL executed: `VACUUM ANALYZE orders` — this specific SQL appears in `pg_stat_activity` during the vacuum runs

**Where to see it:**
- Dashboard: `synthnet-network-overview` — PostgreSQL bgwriter stats panel; `buffers_clean` shows sawtooth pattern as dead tuples accumulate then are cleaned every 30 seconds
- ES query: `GET /metrics-postgresql.activity-default/_search?sort=@timestamp:desc&size=5`

**Scenario markers** (fields/values that confirm it's active):
- `postgresql.stat.table.n_dead_tup` on the `orders` table cycling in a sawtooth pattern — baseline shows near-zero dead tuples
- `postgresql.stat.bgwriter.maxwritten_clean` > 0 — baseline bgwriter activity is minimal in a low-write synthetic workload

---

## pg.seqscan_regression — Sequential scan regression

**Schedule:** Every 3h ± up to 45 min. Duration: ~20 minutes (1200 s).

**What happens:** The workload generator runs multiple `SELECT COUNT(*) FROM orders WHERE notes ILIKE '%note-%'` queries per second. This ILIKE pattern has a leading wildcard that prevents index use even on indexed columns, forcing a full sequential scan (`SEQSCAN`) on the `orders` table for every invocation. The `notes` column is intentionally left unindexed. The sustained scan load increases sequential scan counters and drives up query execution time.

**Data touched:**
- Data stream: `metrics-postgresql.activity-default`
- `postgresql.stat.table.seq_scan`: increases by `SEQSCAN_SCANS_PER_TICK` per sample on the `orders` table — baseline runs one slow scan every 5 minutes; during the scenario this runs multiple times per second
- `postgresql.stat.table.seq_tup_read`: rises in proportion to the scan count × row count in `orders`
- `postgresql.activity.query`: `"SELECT COUNT(*) FROM orders WHERE notes ILIKE '%note-%'"` — this specific query appears at high frequency in `pg_stat_activity` during the window
- `postgresql.activity.state`: `"active"` for the scanning sessions — multiple concurrent active sessions with the same query pattern

**Where to see it:**
- Dashboard: `synthnet-network-overview` — PostgreSQL table stats panel; `seq_scan` counter on `orders` table shows a sharp rate increase for the 20-minute window
- ES query: `GET /metrics-postgresql.activity-default/_search?q=postgresql.activity.query:*ILIKE*&size=10`

**Scenario markers** (fields/values that confirm it's active):
- `postgresql.stat.table.seq_scan` rate on `orders` exceeds 10 per 5-minute sample — baseline is 1 every 5 minutes
- `postgresql.activity.query` containing `"ILIKE '%note-%'"` at high concurrency — no baseline workload uses ILIKE on the `notes` field
