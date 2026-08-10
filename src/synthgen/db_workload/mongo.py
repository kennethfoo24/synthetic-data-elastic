"""MongoDB-specific helpers for the db_workload generator.

Pure functions (build_order_doc, build_slow_scan_filter) are unit-testable
without a live MongoDB instance.
"""

from __future__ import annotations

import random
from datetime import datetime

MONGO_URI_DEFAULT = "mongodb://mongodb-prod:27017/?replicaSet=rs0"

# Issue one deliberately slow COLLSCAN every N seconds (~5 min).
# The collscan targets an unindexed field and generates slow-query log entries
# that populate MongoDB slow-query dashboards in Kibana.
SLOW_SCAN_INTERVAL: int = 300

_STATUSES = ["pending", "confirmed", "shipped", "delivered", "cancelled"]


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
    """Return a MongoDB filter that forces a COLLSCAN on the notes field.

    The regex targets all notes (``^note-``) so it matches every document and
    MongoDB cannot use a collection scan shortcut.  There is intentionally no
    index on ``notes``.
    """
    return {"notes": {"$regex": "^note-[0-9a-f]"}}


def ensure_orders_collection(collection) -> None:
    """Create an index on ``status`` for point-lookups (notes stays unindexed).

    Idempotent — ``create_index`` is a no-op when the index already exists.
    """
    collection.create_index("status", background=True)
    collection.create_index("order_id", background=True)
