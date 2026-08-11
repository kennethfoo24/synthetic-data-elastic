"""PostgreSQL-specific helpers for the db_workload generator.

Pure functions (build_insert_params, build_slow_scan_sql, plan_pg_actions,
CREATE_TABLE_SQL) are unit-testable without a live PostgreSQL connection.
Executor functions (execute_seqscan_regression, execute_vacuum_load,
execute_deadlock_pair) accept psycopg connection objects so they can be tested
with mocks.
"""

from __future__ import annotations

import logging
import random
import threading
from dataclasses import dataclass
from datetime import datetime

from synthgen.common.scenarios import active_scenarios

# devpass123: committed non-sensitive dev credential for the synthetic sandbox.
# Change via PG_DSN env var when running outside the default lab cluster.
PG_DSN_DEFAULT = "postgresql://postgres:devpass123@postgres-prod:5432/postgres"

# Issue one deliberately slow SEQSCAN every N seconds (~5 min).
SLOW_SCAN_INTERVAL: int = 300

# DDL for the orders table.  Idempotent via IF NOT EXISTS.
# The ``notes`` column is deliberately left unindexed so that
# build_slow_scan_sql() forces a SEQSCAN, generating slow-query entries for
# pg_stat_statements / Kibana dashboards.
CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS orders (
    id         SERIAL        PRIMARY KEY,
    order_id   TEXT          NOT NULL,
    customer   TEXT          NOT NULL,
    status     TEXT          NOT NULL,
    total      NUMERIC(10,2),
    notes      TEXT,
    created_at TIMESTAMPTZ   DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS orders_status_idx ON orders (status);
CREATE INDEX IF NOT EXISTS orders_order_id_idx ON orders (order_id);
"""

# ── Scenario-specific bounds ────────────────────────────────────────────────
# Extra SEQSCAN ILIKE queries per tick during the seqscan_regression scenario.
SEQSCAN_SCANS_PER_TICK: int = 3
# Rows bulk-inserted and immediately deleted per tick during vacuum_load,
# leaving dead tuples that accumulate until VACUUM cleans them up.
VACUUM_CHURN_ROWS: int = 100
# Seconds between deadlock attempts within the pg.deadlock window (keeps the
# rate sane while still generating multiple deadlock events per window).
_DEADLOCK_PERIOD_S: int = 30
# Seconds between VACUUM ANALYZE runs within the vacuum_load window.
_VACUUM_PERIOD_S: int = 60

_STATUSES = ["pending", "confirmed", "shipped", "delivered", "cancelled"]

_log = logging.getLogger(__name__)


# ── Pure document / query builders ──────────────────────────────────────────


def build_insert_params(rng: random.Random, tick: datetime) -> dict:
    """Return a parameter dict for an INSERT into orders.

    Deterministic given *rng* state.  The ``notes`` field is unindexed and
    used by ``build_slow_scan_sql`` for SEQSCAN workload.
    """
    return {
        "order_id": f"ORD-{rng.randint(100_000, 999_999)}",
        "customer": f"customer-{rng.randint(1, 1000)}",
        "status": rng.choice(_STATUSES),
        "total": round(rng.uniform(1.0, 5000.0), 2),
        # Unindexed free-text field — target for slow SEQSCAN queries.
        "notes": f"note-{rng.randbytes(4).hex()}",
        "created_at": tick.isoformat(),
    }


def build_slow_scan_sql() -> str:
    """Return SQL that forces a SEQSCAN on the unindexed notes column.

    ILIKE with a leading wildcard prevents index usage even if an index were
    to be added later, making this a reliable slow-query generator.
    """
    return "SELECT COUNT(*) FROM orders WHERE notes ILIKE '%note-%'"


# ── Scenario planner (pure) ──────────────────────────────────────────────────


@dataclass
class PgPlan:
    """Describes what PostgreSQL scenario ops to execute this tick.

    All fields are simple counts / flags — no DB objects, no side effects.
    """

    slow_scan_count: int = 0  # extra ILIKE SEQSCANs this tick
    deadlock_attempt: bool = False  # attempt a genuine deadlock pair this tick
    vacuum_analyze: bool = False  # run VACUUM ANALYZE orders this tick
    churn_rows: int = 0  # rows to bulk-insert + delete for vacuum_load churn


def plan_pg_actions(t: datetime, seed: int) -> PgPlan:
    """Return a PgPlan describing what PostgreSQL scenario ops to run this tick.

    Pure — no side effects, no DB calls.  ``t`` must be timezone-aware.
    Deadlock and VACUUM are rate-limited within their windows so the DB is not
    overwhelmed every single tick.
    """
    active = {spec.id for spec, _phase in active_scenarios("postgresql", t, seed)}
    plan = PgPlan()
    ts = int(t.timestamp())

    if "pg.seqscan_regression" in active:
        plan.slow_scan_count = SEQSCAN_SCANS_PER_TICK

    if "pg.deadlock" in active:
        # One deadlock pair every _DEADLOCK_PERIOD_S seconds.
        plan.deadlock_attempt = ts % _DEADLOCK_PERIOD_S == 0

    if "pg.vacuum_load" in active:
        plan.churn_rows = VACUUM_CHURN_ROWS
        # VACUUM every _VACUUM_PERIOD_S seconds (must run outside a transaction).
        plan.vacuum_analyze = ts % _VACUUM_PERIOD_S == 0

    return plan


# ── Executors ────────────────────────────────────────────────────────────────


def execute_seqscan_regression(conn, count: int) -> None:
    """Run *count* unindexed ILIKE scans to elevate pg_stat_statements metrics.

    Each scan is committed individually.  Failures are logged and the cursor
    is rolled back so *conn* is left in a clean state.
    """
    sql = build_slow_scan_sql()
    for i in range(count):
        try:
            with conn.cursor() as cur:
                cur.execute(sql)
            conn.commit()
            _log.debug("seqscan_regression scan %d done", i)
        except Exception as exc:  # noqa: BLE001
            _log.warning("seqscan_regression scan %d failed: %s", i, exc)
            try:
                conn.rollback()
            except Exception:  # noqa: BLE001, S110
                pass


def execute_vacuum_load(
    conn,
    dsn: str,
    rng: random.Random,
    tick: datetime,
    churn_rows: int,
    do_vacuum: bool,
    *,
    _connect=None,
) -> None:
    """Bulk churn rows (insert + delete) and optionally VACUUM ANALYZE orders.

    The churn creates dead tuples that AUTOVACUUM would normally reclaim; the
    explicit VACUUM ANALYZE call is a direct trigger for pg_stat_bgwriter and
    pg_stat_tables.last_vacuum metrics.

    ``_connect`` is an optional override for ``psycopg.connect`` used in tests
    to avoid opening a real database connection for the VACUUM step.
    """
    import psycopg as _psycopg

    churn_marker = f"churn-{int(tick.timestamp())}"
    _insert_sql = (
        "INSERT INTO orders (order_id, customer, status, total, notes, created_at)"
        " VALUES (%(order_id)s, %(customer)s, %(status)s, %(total)s, %(notes)s, %(created_at)s)"
    )

    # ── bulk insert ──────────────────────────────────────────────────────────
    if churn_rows > 0:
        params_list = []
        for _ in range(churn_rows):
            p = build_insert_params(rng, tick)
            p["notes"] = churn_marker
            params_list.append(p)
        try:
            with conn.cursor() as cur:
                for p in params_list:
                    cur.execute(_insert_sql, p)
            conn.commit()
            _log.debug("vacuum_load: inserted %d churn rows", churn_rows)
        except Exception as exc:  # noqa: BLE001
            _log.warning("vacuum_load: bulk insert failed: %s", exc)
            try:
                conn.rollback()
            except Exception:  # noqa: BLE001, S110
                pass

        # ── delete the churn rows (leaves dead tuples for VACUUM) ────────────
        try:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM orders WHERE notes = %s", (churn_marker,))
            conn.commit()
            _log.debug("vacuum_load: deleted churn rows (marker=%s)", churn_marker)
        except Exception as exc:  # noqa: BLE001
            _log.warning("vacuum_load: bulk delete failed: %s", exc)
            try:
                conn.rollback()
            except Exception:  # noqa: BLE001, S110
                pass

    # ── VACUUM ANALYZE (must run outside a transaction; use a fresh connection) ─
    if do_vacuum:
        _connect_fn = _connect if _connect is not None else _psycopg.connect
        try:
            vconn = _connect_fn(dsn, autocommit=True)
            try:
                vconn.execute("VACUUM ANALYZE orders")
                _log.info("vacuum_load: VACUUM ANALYZE orders done")
            finally:
                try:
                    vconn.close()
                except Exception:  # noqa: BLE001, S110
                    pass
        except Exception as exc:  # noqa: BLE001
            _log.warning("vacuum_load: VACUUM ANALYZE failed: %s", exc)


def _run_deadlock_session(
    conn,
    first_lock: int,
    second_lock: int,
    ready_evt: threading.Event,
    go_evt: threading.Event,
    label: str,
) -> None:
    """Run one half of a deadlock pair in a dedicated thread.

    Acquires *first_lock*, signals *ready_evt*, waits for *go_evt* (the other
    session has its first lock), then acquires *second_lock*.  PostgreSQL's
    deadlock detector fires ~1 s after the circular wait forms and aborts one
    of the two sessions with ``ERROR: deadlock detected``.

    The exception is caught, the transaction is rolled back, and the connection
    is closed — always, even if the wait times out.

    Pure helper — does not open connections; accepts one as a parameter so it
    is testable with a mock.
    """
    try:
        cur = conn.cursor()
        cur.execute(f"SELECT pg_advisory_xact_lock({first_lock})")
        ready_evt.set()
        go_evt.wait(timeout=5.0)
        cur.execute(f"SELECT pg_advisory_xact_lock({second_lock})")
        conn.commit()
    except Exception as exc:  # noqa: BLE001
        _log.info("deadlock session-%s resolved: %s", label, type(exc).__name__)
        try:
            conn.rollback()
        except Exception:  # noqa: BLE001, S110
            pass
    finally:
        try:
            conn.close()
        except Exception:  # noqa: BLE001, S110
            pass


def execute_deadlock_pair(dsn: str, *, _connect=None) -> None:
    """Open two psycopg connections and trigger a genuine PostgreSQL deadlock.

    Session A: acquires advisory lock 1001, then tries 1002.
    Session B: acquires advisory lock 1002, then tries 1001.

    PostgreSQL's deadlock detector (runs every ``deadlock_timeout``, default 1 s)
    detects the circular wait and aborts one session with ``deadlock detected``.
    Both connections are rolled back and closed unconditionally.

    ``_connect`` is an optional override for ``psycopg.connect`` used in tests.
    """
    import psycopg as _psycopg

    connect_fn = _connect if _connect is not None else _psycopg.connect
    try:
        conn_a = connect_fn(dsn, autocommit=False)
        conn_b = connect_fn(dsn, autocommit=False)
    except Exception as exc:  # noqa: BLE001
        _log.warning("deadlock_pair: could not open connections: %s", exc)
        return

    a_ready = threading.Event()
    b_ready = threading.Event()

    t_a = threading.Thread(
        target=_run_deadlock_session,
        args=(conn_a, 1001, 1002, a_ready, b_ready, "A"),
        daemon=True,
    )
    t_b = threading.Thread(
        target=_run_deadlock_session,
        args=(conn_b, 1002, 1001, b_ready, a_ready, "B"),
        daemon=True,
    )
    t_a.start()
    t_b.start()
    t_a.join(timeout=10.0)
    t_b.join(timeout=10.0)
    _log.info("deadlock_pair: both sessions finished (a_alive=%s b_alive=%s)", t_a.is_alive(), t_b.is_alive())
