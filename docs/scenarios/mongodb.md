# MongoDB Scenarios

Data stream: `metrics-mongodb.status-default`
Source: `mongodb-prod` (replica-primary, `10.10.7.11`) in replica set `rs0` via `mongodb://mongodb-prod:27017/?replicaSet=rs0`

The MongoDB workload generator connects to the live MongoDB instance. All three scenarios drive real database activity that surfaces in MongoDB's own telemetry, collected by the Elastic `mongodb` metrics integration.

---

## mongo.slow_query_storm — Slow query storm (COLLSCAN)

**Schedule:** Every 3h ± up to 45 min. Duration: ~25 minutes (1500 s).

**What happens:** During the window, the workload generator runs additional full collection scans (`count_documents`) on the `orders` collection's `notes` field — an intentionally unindexed field — at a rate of several extra COLLSCANs per second. This causes a sustained spike in query execution time and scan overhead visible in MongoDB metrics and slow query logs.

**Data touched:**
- Data stream: `metrics-mongodb.status-default`
- `mongodb.status.operations.counters.query`: elevated count of query operations (COLLSCANs add one query op each)
- `mongodb.status.operations.latencies.reads.latency`: increases during storm as COLLSCANs dominate
- Query filter used: `{"notes": {"$regex": "^note-[0-9a-f]"}}` against the `orders` collection — this regex matches all documents, forcing a full scan on every invocation

**Where to see it:**
- Dashboard: `synthnet-dell-infrastructure` or `synthnet-hpe-infrastructure` — MongoDB operation counters panel; query latency spike visible over the 25-minute window
- ES query: `GET /metrics-mongodb.status-default/_search?sort=@timestamp:desc&size=5`

**Scenario markers** (fields/values that confirm it's active):
- `mongodb.status.operations.counters.query` increasing by hundreds per minute above baseline rate — baseline runs one slow scan every 5 minutes
- `mongodb.status.operations.latencies.reads.latency` sustained above baseline for the 25-minute window

---

## mongo.repl_lag — Replication lag burst

**Schedule:** Every 3h ± up to 45 min. Duration: ~30 minutes (1800 s).

**What happens:** The workload generator bulk-inserts up to 20 synthetic `orders` documents per second into the primary, creating a write surge that overwhelms the replica's apply queue and induces measurable replication lag. The burst sustains for 30 minutes (~36,000 documents total), well within the 24-hour TTL index retention budget.

**Data touched:**
- Data stream: `metrics-mongodb.status-default`
- `mongodb.status.repl.apply.ops`: elevated — the replica's apply queue grows as inserts outpace replication throughput
- `mongodb.status.repl.lag`: measurable secondary-behind-primary lag in seconds (appears in replica-set status metrics)
- `mongodb.status.operations.counters.insert`: spikes to ~20 ops/s vs. baseline of < 1 op/s
- Document schema: `{order_id, customer, status, items[], total, notes, created_at}` — `notes` is the unindexed field targeted by slow scans

**Where to see it:**
- Dashboard: `synthnet-network-overview` — MongoDB replication lag panel; insert op counter spike; look for `mongodb.status.repl.lag` > 0 sustained over 30 min
- ES query: `GET /metrics-mongodb.status-default/_search?sort=@timestamp:desc&size=5`

**Scenario markers** (fields/values that confirm it's active):
- `mongodb.status.operations.counters.insert` > 15 per 5-minute sample — baseline inserts are < 1/s
- `mongodb.status.repl.lag` > 0 sustained over multiple consecutive metric samples

---

## mongo.conn_exhaustion — Connection pool exhaustion

**Schedule:** Every 3h ± up to 45 min. Duration: ~25 minutes (1500 s).

**What happens:** The workload generator opens up to 40 additional `MongoClient` connections to `mongodb-prod` at the start of the window (capped at `CONN_EXHAUSTION_CAP = 40` to stay safely below the server's `maxIncomingConnections` default of 65536 and the pod's fd limit). All extra connections are held open for the window duration then released. This drives the connection count metric well above the typical single-connection baseline.

**Data touched:**
- Data stream: `metrics-mongodb.status-default`
- `mongodb.status.connections.current`: rises to baseline + 40 during the window — baseline is typically 1–3 connections
- `mongodb.status.connections.available`: decreases by the same amount (total connections minus current)
- `mongodb.status.connections.total_created`: cumulative connection creation count spikes at window start as 40 connections are opened simultaneously

**Where to see it:**
- Dashboard: `synthnet-network-overview` — MongoDB connections panel; `connections.current` jump to ~40+ above baseline at window start, then drop back to normal at window end
- ES query: `GET /metrics-mongodb.status-default/_search?sort=@timestamp:desc&size=5`

**Scenario markers** (fields/values that confirm it's active):
- `mongodb.status.connections.current` ≥ 40 — baseline is typically 1–3; this value only reaches 40+ during the conn_exhaustion window
- `mongodb.status.connections.total_created` shows a step increase of ~40 at the scenario start timestamp
