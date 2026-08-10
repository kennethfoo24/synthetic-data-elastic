"""db_workload: continuous CRUD workload against MongoDB and PostgreSQL.

Entry point is ``run()``, called from ``__main__`` in ``db-workload`` mode.
The workload runs forever, generating ~5-20 ops/s (scaled by rate_multiplier)
against both the mongodb-prod and postgres-prod instances.  Every ~5 minutes
a deliberately slow unindexed scan is issued against each DB to produce
slow-query metrics visible in Kibana dashboards (full slow-query analysis
comes in Plan 4).

Retry-with-backoff is used for initial connections; individual op failures are
logged and ignored so the loop never crashes.
"""

from __future__ import annotations

import logging
import os
import time
from datetime import UTC, datetime

from synthgen import GLOBAL_SEED
from synthgen.common.patterns import rate_multiplier
from synthgen.db_workload.mongo import (
    MONGO_URI_DEFAULT,
    build_order_doc,
    build_slow_scan_filter,
    ensure_orders_collection,
)
from synthgen.db_workload.mongo import (
    SLOW_SCAN_INTERVAL as MONGO_SLOW_INTERVAL,
)
from synthgen.db_workload.postgres import (
    CREATE_TABLE_SQL,
    PG_DSN_DEFAULT,
    build_insert_params,
    build_slow_scan_sql,
)
from synthgen.db_workload.postgres import (
    SLOW_SCAN_INTERVAL as PG_SLOW_INTERVAL,
)

_log = logging.getLogger(__name__)

_BACKOFF_MAX = 30  # seconds


def _connect_mongo(uri: str):
    """Return a connected pymongo MongoClient, retrying with backoff."""
    import pymongo

    delay = 2
    while True:
        try:
            client = pymongo.MongoClient(uri, serverSelectionTimeoutMS=5000)
            client.admin.command("ping")
            _log.info("mongo connected: %s", uri)
            return client
        except Exception as exc:  # noqa: BLE001
            _log.warning("mongo connect failed (%s), retry in %ds", exc, delay)
            time.sleep(delay)
            delay = min(delay * 2, _BACKOFF_MAX)


def _connect_pg(dsn: str):
    """Return a connected psycopg connection, retrying with backoff."""
    import psycopg

    delay = 2
    while True:
        try:
            conn = psycopg.connect(dsn, autocommit=False)
            _log.info("postgres connected: %s", dsn.split("@")[-1])
            return conn
        except Exception as exc:  # noqa: BLE001
            _log.warning("postgres connect failed (%s), retry in %ds", exc, delay)
            time.sleep(delay)
            delay = min(delay * 2, _BACKOFF_MAX)


def run(seed: int = GLOBAL_SEED) -> None:
    """Run the continuous workload loop.  Never returns normally."""
    import random

    import psycopg
    import pymongo

    mongo_uri = os.environ.get("MONGO_URI", MONGO_URI_DEFAULT)
    pg_dsn = os.environ.get("PG_DSN", PG_DSN_DEFAULT)

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    # --- connect (with retry) ---
    mongo_client = _connect_mongo(mongo_uri)
    pg_conn = _connect_pg(pg_dsn)

    # --- one-time setup ---
    db = mongo_client["synthlab"]
    collection = db["orders"]
    ensure_orders_collection(collection)

    with pg_conn.cursor() as cur:
        cur.execute(CREATE_TABLE_SQL)
    pg_conn.commit()

    rng = random.Random(seed)
    mongo_last_slow: float = 0.0
    pg_last_slow: float = 0.0
    total_ticks = 0
    # Hourly PG retention: track by hour so the DELETE fires once per clock hour
    # (deterministic from wall-clock time, not a separate interval counter).
    last_cleanup_hour: int = -1

    _log.info("db-workload started (seed=%d)", seed)

    while True:
        tick = datetime.now(UTC)
        mult = rate_multiplier(tick, "app", "db-workload", seed)
        # ~5-20 ops/s scaled by mult (1.0 → 10 base ops)
        base_ops = max(1, int(10 * mult))

        # ---- MongoDB ops ----
        for _ in range(base_ops):
            op = rng.choice(["insert", "read", "update"])
            try:
                if op == "insert":
                    collection.insert_one(build_order_doc(rng, tick))
                elif op == "read":
                    collection.find_one({"status": rng.choice(["pending", "confirmed"])})
                else:
                    collection.update_one(
                        {"status": "pending"},
                        {"$set": {"status": "confirmed"}},
                    )
            except pymongo.errors.PyMongoError as exc:
                _log.warning("mongo op failed: %s", exc)

        # Mongo slow scan every ~5 min — count_documents visits EVERY doc
        # (genuine COLLSCAN on unindexed notes field; find_one would short-circuit
        # at the first match and never scan the full collection).
        now = time.monotonic()
        if now - mongo_last_slow >= MONGO_SLOW_INTERVAL:
            mongo_last_slow = now
            try:
                n = collection.count_documents(build_slow_scan_filter())
                _log.info("mongo slow scan done (matched %d docs)", n)
            except pymongo.errors.PyMongoError as exc:
                _log.warning("mongo slow scan failed: %s", exc)

        # ---- PostgreSQL ops ----
        for _ in range(base_ops):
            op = rng.choice(["insert", "read", "update"])
            try:
                params = build_insert_params(rng, tick)
                with pg_conn.cursor() as cur:
                    if op == "insert":
                        cur.execute(
                            "INSERT INTO orders "
                            "(order_id, customer, status, total, notes, created_at) "
                            "VALUES (%(order_id)s, %(customer)s, %(status)s, "
                            "%(total)s, %(notes)s, %(created_at)s)",
                            params,
                        )
                    elif op == "read":
                        cur.execute(
                            "SELECT id, order_id, status, total FROM orders "
                            "WHERE status = %(status)s LIMIT 10",
                            {"status": params["status"]},
                        )
                    else:
                        cur.execute(
                            "UPDATE orders SET status = 'confirmed' "
                            "WHERE ctid = (SELECT ctid FROM orders "
                            "WHERE status = 'pending' LIMIT 1)"
                        )
                pg_conn.commit()
            except psycopg.Error as exc:
                _log.warning("pg op failed: %s", exc)
                try:
                    pg_conn.rollback()
                except psycopg.Error:
                    pass

        # PG slow scan every ~5 min (SEQSCAN on unindexed text column)
        if now - pg_last_slow >= PG_SLOW_INTERVAL:
            pg_last_slow = now
            try:
                with pg_conn.cursor() as cur:
                    cur.execute(build_slow_scan_sql())
                pg_conn.commit()
                _log.info("pg slow scan done")
            except psycopg.Error as exc:
                _log.warning("pg slow scan failed: %s", exc)
                try:
                    pg_conn.rollback()
                except psycopg.Error:
                    pass

        # PG retention: once per clock hour DELETE rows older than 24 h.
        # Deterministic from wall-clock time — fires exactly when the hour changes.
        if tick.hour != last_cleanup_hour:
            last_cleanup_hour = tick.hour
            try:
                with pg_conn.cursor() as cur:
                    cur.execute(
                        "DELETE FROM orders WHERE created_at < NOW() - INTERVAL '24 hours'"
                    )
                pg_conn.commit()
                _log.info("pg retention cleanup done (hour=%d)", tick.hour)
            except psycopg.Error as exc:
                _log.warning("pg retention cleanup failed: %s", exc)
                try:
                    pg_conn.rollback()
                except psycopg.Error:
                    pass

        total_ticks += 1
        if total_ticks % 300 == 0:
            _log.info("db-workload tick=%d mult=%.2f base_ops=%d", total_ticks, mult, base_ops)

        time.sleep(1.0)
