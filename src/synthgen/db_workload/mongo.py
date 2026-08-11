"""MongoDB-specific helpers for the db_workload generator.

Pure functions (build_order_doc, build_slow_scan_filter, plan_mongo_actions) are
unit-testable without a live MongoDB instance.  Executor functions
(execute_slow_storm, execute_repl_lag_inserts, open_extra_connections,
close_extra_connections) accept pymongo collection/client objects so they can be
tested with mocks.
"""

from __future__ import annotations

import logging
import random
from dataclasses import dataclass
from datetime import datetime

from synthgen.common.scenarios import active_scenarios

MONGO_URI_DEFAULT = "mongodb://mongodb-prod:27017/?replicaSet=rs0"

# Issue one deliberately slow COLLSCAN every N seconds (~5 min).
# The collscan targets an unindexed field and generates slow-query log entries
# that populate MongoDB slow-query dashboards in Kibana.
SLOW_SCAN_INTERVAL: int = 300

# ── Scenario-specific bounds ────────────────────────────────────────────────
# CONN_EXHAUSTION_CAP: hard ceiling on extra MongoClient connections.  Must
# stay well below the server's maxIncomingConnections (default 65536) and the
# per-pod fd limit; 40 is safe for a single-node sandbox with a few other
# workload connections already open.
CONN_EXHAUSTION_CAP: int = 40
# REPL_LAG_MAX_INSERTS: docs inserted per tick (1 s) during the repl_lag
# scenario.  At 20 docs/s × ~1 800 s window the burst is ~36 000 docs — well
# within the TTL retention budget and far below rs0 lag thresholds.
REPL_LAG_MAX_INSERTS: int = 20
# STORM_SCANS_PER_TICK: extra full COLLSCANs per tick during slow_query_storm.
STORM_SCANS_PER_TICK: int = 3

_STATUSES = ["pending", "confirmed", "shipped", "delivered", "cancelled"]

_log = logging.getLogger(__name__)


# ── Pure document / query builders ──────────────────────────────────────────


def build_order_doc(rng: random.Random, tick: datetime) -> dict:
    """Build a synthetic orders document.  Deterministic given *rng* state.

    The ``notes`` field is unindexed so that ``build_slow_scan_filter`` targets
    it for a realistic COLLSCAN.
    """
    items = [
        {
            "sku": f"SKU-{rng.randint(1000, 9999)}",
            "qty": rng.randint(1, 10),
            "price": round(rng.uniform(1.0, 500.0), 2),
        }
        for _ in range(rng.randint(1, 5))
    ]
    return {
        "order_id": f"ORD-{rng.randint(100_000, 999_999)}",
        "customer": f"customer-{rng.randint(1, 1000)}",
        "status": rng.choice(_STATUSES),
        "items": items,
        "total": round(sum(i["price"] * i["qty"] for i in items), 2),
        # Unindexed free-text field — target for slow COLLSCAN queries.
        "notes": f"note-{rng.randbytes(4).hex()}",
        "created_at": tick.isoformat(),
    }


def build_slow_scan_filter() -> dict:
    """Return a MongoDB filter that forces a full COLLSCAN on the notes field.

    The regex matches every document so the driver cannot short-circuit after
    returning the first hit (unlike find_one, count_documents must visit the
    entire collection).  There is intentionally no index on ``notes``.
    """
    return {"notes": {"$regex": "^note-[0-9a-f]"}}


def ensure_orders_collection(collection) -> None:
    """Create indexes for point-lookups; TTL for retention; notes stays unindexed.

    * status / order_id — indexed for normal read/update ops.
    * created_at — TTL index (24 h) prevents unbounded growth against the 2 Gi
      emptyDir backing store.
    * notes — intentionally left unindexed so count_documents(slow_scan_filter)
      forces a genuine COLLSCAN.

    Idempotent — create_index is a no-op when the index already exists.
    """
    collection.create_index("status")
    collection.create_index("order_id")
    collection.create_index("created_at", expireAfterSeconds=86400)


# ── Scenario planner (pure) ──────────────────────────────────────────────────


@dataclass
class MongoPlan:
    """Describes what MongoDB scenario ops to execute this tick.

    All fields are simple counts / flags — no DB objects, no side effects.
    """

    slow_scan_count: int = 0  # extra count_documents COLLSCANs this tick
    repl_lag_inserts: int = 0  # docs to bulk-insert for the repl_lag scenario
    conn_open_count: int = 0  # extra MongoClients to open (conn_exhaustion)
    conn_close_all: bool = False  # release all held extra connections


def plan_mongo_actions(
    t: datetime,
    seed: int,
    current_extra_conns: int = 0,
) -> MongoPlan:
    """Return a MongoPlan describing what MongoDB scenario ops to run this tick.

    Pure — no side effects, no DB calls.  ``t`` must be timezone-aware.
    ``current_extra_conns`` is the number of extra MongoClient connections
    currently held open (used to compute how many more to open).
    """
    active = {spec.id for spec, _phase in active_scenarios("mongodb", t, seed)}
    plan = MongoPlan()

    if "mongo.slow_query_storm" in active:
        plan.slow_scan_count = STORM_SCANS_PER_TICK

    if "mongo.repl_lag" in active:
        plan.repl_lag_inserts = REPL_LAG_MAX_INSERTS

    if "mongo.conn_exhaustion" in active:
        # Ramp up to the cap; no-op if already at cap.
        plan.conn_open_count = max(0, CONN_EXHAUSTION_CAP - current_extra_conns)
    elif current_extra_conns > 0:
        # Scenario window ended — schedule a full release.
        plan.conn_close_all = True

    return plan


# ── Executors ────────────────────────────────────────────────────────────────


def execute_slow_storm(collection, count: int) -> None:
    """Run *count* full COLLSCAN count_documents calls on the orders collection.

    Each call visits every document via the unindexed ``notes`` field, producing
    slow-query log entries that appear in MongoDB slow-query dashboards.
    Failures are logged and swallowed so the caller's loop never crashes.
    """
    filt = build_slow_scan_filter()
    for i in range(count):
        try:
            n = collection.count_documents(filt)
            _log.debug("slow_storm collscan %d: matched %d docs", i, n)
        except Exception as exc:  # noqa: BLE001
            _log.warning("slow_storm collscan %d failed: %s", i, exc)


def execute_repl_lag_inserts(
    collection,
    rng: random.Random,
    tick: datetime,
    count: int,
) -> None:
    """Bulk-insert *count* synthetic orders to generate measurable replication lag.

    Uses insert_many with ordered=False so a partial failure does not abort the
    whole batch.  Bounded by REPL_LAG_MAX_INSERTS; retention TTL keeps total
    collection size under control.
    """
    docs = [build_order_doc(rng, tick) for _ in range(count)]
    try:
        collection.insert_many(docs, ordered=False)
        _log.debug("repl_lag: inserted %d docs", count)
    except Exception as exc:  # noqa: BLE001
        _log.warning("repl_lag: insert_many failed: %s", exc)


def open_extra_connections(mongo_uri: str, n: int) -> list:
    """Open up to *n* new MongoClient connections and return the list.

    Each connection is validated (ping) before being counted.  On failure the
    loop stops early and returns whatever was successfully opened.
    Hard-capped by CONN_EXHAUSTION_CAP in the planner, so *n* is always safe.
    """
    import pymongo

    opened: list = []
    for _ in range(n):
        try:
            c = pymongo.MongoClient(mongo_uri, serverSelectionTimeoutMS=3000)
            opened.append(c)
        except Exception as exc:  # noqa: BLE001
            _log.warning("conn_exhaustion: open failed: %s", exc)
            break  # do not attempt further opens if the server is rejecting us
    if opened:
        _log.info("conn_exhaustion: opened %d extra connections", len(opened))
    return opened


def close_extra_connections(conns: list) -> None:
    """Close every MongoClient in *conns* and clear the list in-place.

    Called both when the scenario window ends and unconditionally in the run()
    finally-block so connections are always released on process exit.
    """
    count = len(conns)
    for c in conns:
        try:
            c.close()
        except Exception as exc:  # noqa: BLE001
            _log.warning("conn_exhaustion: close failed: %s", exc)
    conns.clear()
    if count:
        _log.info("conn_exhaustion: closed %d extra connections", count)
