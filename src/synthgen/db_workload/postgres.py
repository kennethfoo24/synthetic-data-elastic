"""PostgreSQL-specific helpers for the db_workload generator.

Pure functions (build_insert_params, build_slow_scan_sql, CREATE_TABLE_SQL)
are unit-testable without a live PostgreSQL connection.
"""

from __future__ import annotations

import random
from datetime import datetime

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

_STATUSES = ["pending", "confirmed", "shipped", "delivered", "cancelled"]


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
