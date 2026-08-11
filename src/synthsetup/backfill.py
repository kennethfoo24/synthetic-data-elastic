"""7-day backfill for synthetic network observability data.

Sampling strategy
-----------------
LOGS (cisco_asa, cisco_ios, panw, cisco_meraki):
    Stride = 60 s — one ``generate_batch`` call per stride-tick per source.
    Clock steps from ``now - days*86400`` to ``now`` in 60-second increments.
    Each call generates 1 second's worth of docs (the same as one live tick);
    the batch is written once per stride step, no multiplication.

    Expected doc counts (7 days, stride 60 s):
      - Ticks:  7 × 24 × 60 = 10,080 per source
      - ASA:    10,080 × 1 device  × PEAK  8 × ~0.5 mean mult  ≈   40,000
      - IOS:    10,080 × 7 devices × PEAK  2 × ~0.5             ≈   70,000
      - PANW:   10,080 ×              avg  ~7 records/tick       ≈   70,000
      - Meraki: 10,080 × 3 devices × avg  ~4 records/device     ≈  120,000
      Total syslog ≈ 300,000 docs; runtime ≈ 1–2 min at typical ES throughput.

NETFLOW (logs-netflow.log-default):
    Stride = 300 s.  ``generate_records`` → ECS-shaped docs.
    Expected: 2,016 ticks × ~28 records/tick (14 flows × 2 directions) ≈ 56,000 docs.

SNMP (metrics-snmp.device-default):
    Stride = 300 s.  One doc per non-DB/non-Meraki device per tick.
    Expected: 2,016 ticks × 20 devices ≈ 40,000 docs.

Grand total ≈ 400,000 docs across all streams for a 7-day window.

Idempotency strategy (all streams)
------------------------------------
delete_by_query over the backfill time range before writing any documents.
Rationale: data streams auto-assign ``_id`` on every write; deterministic IDs
are not supported on the default data-stream write path.  delete_by_query is
the only idempotency mechanism available without aliasing tricks and works
uniformly for both pipeline-parsed log streams and synthetic metric streams.
The delete runs once per stream, before bulk indexing begins.

Seam continuity
---------------
``generate_for_tick(source, topo, t, seed)`` is the unified entry point used
by both backfill (historical ``t``) and the live generator (current ``t``).
The underlying ``generate_batch`` pure functions are identical; the only
difference is the timestamp argument, so the last backfilled tick and the
first live tick are guaranteed to be continuous.

Usage
-----
    python -m synthsetup.backfill [--days 7] [--dry-run] [--sources all|logs|metrics]

Env vars required (unless --dry-run): ES_URL, ELASTIC_API_KEY
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

from synthgen import GLOBAL_SEED
from synthgen.common.topology import Topology, load_topology
from synthgen.netflow_gen.source import generate_records as _netflow_records
from synthgen.syslog_gen import asa_source, ios_source, meraki_source, panw_source
from synthsetup.validate import Ctx, validate_mappings

_TOPOLOGY_PATH = Path(__file__).parents[2] / "topology" / "network.yaml"

LOGS_STRIDE_S: int = 60     # 1 sample per minute for syslog sources
METRICS_STRIDE_S: int = 300  # 1 sample per 5 min for NetFlow / SNMP
BULK_CHUNK: int = 500        # docs per bulk request

# ---------------------------------------------------------------------------
# Log sources: (short_name, data_stream, generate_batch_fn)
# ---------------------------------------------------------------------------

_LOG_SOURCES: list[tuple[str, str, object]] = [
    ("cisco_asa", "logs-cisco_asa.log-default", asa_source.generate_batch),
    ("cisco_ios", "logs-cisco_ios.log-default", ios_source.generate_batch),
    ("panw", "logs-panw.panos-default", panw_source.generate_batch),
    ("cisco_meraki", "logs-cisco_meraki.log-default", meraki_source.generate_batch),
]

# ---------------------------------------------------------------------------
# Seam-continuity entry point
# ---------------------------------------------------------------------------


def generate_for_tick(
    source: str, topo: Topology, t: datetime, seed: int = GLOBAL_SEED
) -> list[str]:
    """Return syslog lines for *source* at time *t*.

    This is the unified entry point used by both backfill (historical ``t``)
    and the live generator (current ``t``).  Calling this function or calling
    the underlying ``generate_batch`` directly with the same arguments yields
    identical output, guaranteeing seam continuity between the last backfilled
    tick and the first live tick.
    """
    dispatch: dict[str, object] = {
        "cisco_asa": asa_source.generate_batch,
        "cisco_ios": ios_source.generate_batch,
        "panw": panw_source.generate_batch,
        "cisco_meraki": meraki_source.generate_batch,
    }
    if source not in dispatch:
        raise ValueError(f"Unknown log source: {source!r}")
    return dispatch[source](topo, t, seed)  # type: ignore[operator]


# ---------------------------------------------------------------------------
# Bulk helpers
# ---------------------------------------------------------------------------


def _build_bulk_body(docs: list[tuple[str, dict]]) -> bytes:
    """Build NDJSON body for ``POST /_bulk``.

    *docs* is a list of ``(index_name, source_dict)`` tuples.
    """
    lines: list[str] = []
    for index, source in docs:
        lines.append(json.dumps({"index": {"_index": index}}))
        lines.append(json.dumps(source))
    return ("\n".join(lines) + "\n").encode()


def _flush_bulk(ctx: Ctx, docs: list[tuple[str, dict]]) -> None:
    """POST *docs* to ``/_bulk``; abort with ``RuntimeError`` on any indexing error."""
    body = _build_bulk_body(docs)
    r = ctx.es().post(
        "/_bulk",
        content=body,
        headers={"Content-Type": "application/x-ndjson"},
    )
    if r.status_code >= 400:
        raise RuntimeError(f"Bulk request failed: HTTP {r.status_code}: {r.text[:500]}")
    result = r.json()
    if result.get("errors"):
        for item in result.get("items", []):
            for detail in item.values():
                err = detail.get("error")
                if err:
                    raise RuntimeError(
                        f"Bulk indexing error: {err.get('type', 'unknown')}: "
                        f"{err.get('reason', str(err))}"
                    )
        raise RuntimeError("Bulk indexing errors: check ES response items")


def _bulk_in_chunks(
    ctx: Ctx,
    docs: list[tuple[str, dict]],
    dry_run: bool,
) -> None:
    """Send *docs* to ES in ``BULK_CHUNK``-sized batches."""
    for i in range(0, max(1, len(docs)), BULK_CHUNK):
        chunk = docs[i : i + BULK_CHUNK]
        if not dry_run:
            _flush_bulk(ctx, chunk)


# ---------------------------------------------------------------------------
# Idempotency: delete before writing
# ---------------------------------------------------------------------------


def _delete_range(ctx: Ctx, index: str, start_t: datetime, end_t: datetime) -> None:
    """Delete all docs in *index* with ``@timestamp`` in ``[start_t, end_t)``."""
    r = ctx.es().post(
        f"/{index}/_delete_by_query",
        json={
            "query": {
                "range": {
                    "@timestamp": {
                        "gte": start_t.isoformat(),
                        "lt": end_t.isoformat(),
                    }
                }
            }
        },
        params={"wait_for_completion": "true", "conflicts": "proceed"},
    )
    if r.status_code == 404:
        return  # stream does not exist yet — nothing to delete
    if r.status_code >= 400:
        raise RuntimeError(
            f"delete_by_query on {index} failed: HTTP {r.status_code}: {r.text[:200]}"
        )
    deleted = r.json().get("deleted", 0)
    print(f"  Deleted {deleted:,} existing docs from {index}", flush=True)


# ---------------------------------------------------------------------------
# Syslog backfill
# ---------------------------------------------------------------------------


def _backfill_log_source(
    ctx: Ctx,
    topo: Topology,
    source: str,
    stream: str,
    gen_fn: object,
    start_t: datetime,
    end_t: datetime,
    dry_run: bool,
) -> int:
    """Backfill one syslog source into *stream*.  Returns total doc count."""
    print(f"\n── {source} → {stream}", flush=True)

    if not dry_run:
        _delete_range(ctx, stream, start_t, end_t)

    buf: list[tuple[str, dict]] = []
    last_day = -1
    total = 0
    t = start_t

    while t < end_t:
        day = (t - start_t).days
        if day != last_day:
            print(f"  Day {day + 1}  {t.date()}", flush=True)
            last_day = day

        lines: list[str] = gen_fn(topo, t, GLOBAL_SEED)  # type: ignore[operator]
        ts = t.isoformat()
        for line in lines:
            # @timestamp is set explicitly so the doc lands at the correct
            # historical instant even if the ingest pipeline's date parsing
            # re-derives it from the syslog line — both must agree.
            buf.append((stream, {"@timestamp": ts, "message": line}))

        # Flush full chunks eagerly to keep memory bounded
        while len(buf) >= BULK_CHUNK:
            chunk = buf[:BULK_CHUNK]
            if not dry_run:
                _flush_bulk(ctx, chunk)
            total += BULK_CHUNK
            buf = buf[BULK_CHUNK:]

        t += timedelta(seconds=LOGS_STRIDE_S)

    # Flush remainder
    if buf:
        if not dry_run:
            _flush_bulk(ctx, buf)
        total += len(buf)

    print(f"  {source}: {total:,} docs", flush=True)
    return total


# ---------------------------------------------------------------------------
# NetFlow backfill
# ---------------------------------------------------------------------------

_PROTO_MAP: dict[int, str] = {6: "tcp", 17: "udp"}


def _netflow_doc(t: datetime, rec: object) -> dict:
    """Map a ``FlowRecord`` to a minimal ECS document for the netflow data stream."""
    return {
        "@timestamp": t.isoformat(),
        "source": {"ip": rec.src_addr, "port": rec.src_port},  # type: ignore[attr-defined]
        "destination": {"ip": rec.dst_addr, "port": rec.dst_port},  # type: ignore[attr-defined]
        "network": {
            "transport": _PROTO_MAP.get(rec.protocol, "unknown"),  # type: ignore[attr-defined]
            "bytes": rec.in_bytes,  # type: ignore[attr-defined]
            "packets": rec.in_pkts,  # type: ignore[attr-defined]
        },
        "event": {"kind": "event", "category": ["network"]},
    }


def _backfill_netflow(
    ctx: Ctx,
    topo: Topology,
    start_t: datetime,
    end_t: datetime,
    dry_run: bool,
) -> int:
    """Backfill synthesized NetFlow records into ``logs-netflow.log-default``."""
    stream = "logs-netflow.log-default"
    print(f"\n── netflow → {stream}", flush=True)

    if not dry_run:
        sample_recs = _netflow_records(topo, start_t, GLOBAL_SEED)
        if sample_recs:
            validate_mappings(ctx, stream, _netflow_doc(start_t, sample_recs[0]))
        _delete_range(ctx, stream, start_t, end_t)

    buf: list[tuple[str, dict]] = []
    last_day = -1
    total = 0
    t = start_t

    while t < end_t:
        day = (t - start_t).days
        if day != last_day:
            print(f"  Day {day + 1}  {t.date()}", flush=True)
            last_day = day

        for rec in _netflow_records(topo, t, GLOBAL_SEED):
            buf.append((stream, _netflow_doc(t, rec)))

        while len(buf) >= BULK_CHUNK:
            chunk = buf[:BULK_CHUNK]
            if not dry_run:
                _flush_bulk(ctx, chunk)
            total += BULK_CHUNK
            buf = buf[BULK_CHUNK:]

        t += timedelta(seconds=METRICS_STRIDE_S)

    if buf:
        if not dry_run:
            _flush_bulk(ctx, buf)
        total += len(buf)

    print(f"  netflow: {total:,} docs", flush=True)
    return total


# ---------------------------------------------------------------------------
# SNMP backfill
# ---------------------------------------------------------------------------


def _snmp_doc(t: datetime, device_name: str) -> dict:
    """Minimal ECS document for the SNMP metrics data stream."""
    return {
        "@timestamp": t.isoformat(),
        "device": {"name": device_name},
    }


def _snmp_devices(topo: Topology) -> list[str]:
    return [
        d.name
        for d in topo.devices
        if d.role != "database" and d.vendor != "meraki"
    ]


def _backfill_snmp(
    ctx: Ctx,
    topo: Topology,
    start_t: datetime,
    end_t: datetime,
    dry_run: bool,
) -> int:
    """Backfill synthesized SNMP device docs into ``metrics-snmp.device-default``."""
    stream = "metrics-snmp.device-default"
    print(f"\n── snmp → {stream}", flush=True)

    devices = _snmp_devices(topo)

    if not dry_run:
        if devices:
            validate_mappings(ctx, stream, _snmp_doc(start_t, devices[0]))
        _delete_range(ctx, stream, start_t, end_t)

    buf: list[tuple[str, dict]] = []
    last_day = -1
    total = 0
    t = start_t

    while t < end_t:
        day = (t - start_t).days
        if day != last_day:
            print(f"  Day {day + 1}  {t.date()}", flush=True)
            last_day = day

        for dev_name in devices:
            buf.append((stream, _snmp_doc(t, dev_name)))

        while len(buf) >= BULK_CHUNK:
            chunk = buf[:BULK_CHUNK]
            if not dry_run:
                _flush_bulk(ctx, chunk)
            total += BULK_CHUNK
            buf = buf[BULK_CHUNK:]

        t += timedelta(seconds=METRICS_STRIDE_S)

    if buf:
        if not dry_run:
            _flush_bulk(ctx, buf)
        total += len(buf)

    print(f"  snmp: {total:,} docs", flush=True)
    return total


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


def run_backfill(
    ctx: Ctx,
    days: int = 7,
    sources: str = "all",
    dry_run: bool = False,
) -> dict[str, int]:
    """Run the backfill.  Returns ``{stream_name: doc_count}`` for each stream."""
    topo = load_topology(_TOPOLOGY_PATH)
    end_t = datetime.now(UTC).replace(microsecond=0)
    start_t = end_t - timedelta(days=days)

    ticks_log = days * 86400 // LOGS_STRIDE_S
    ticks_met = days * 86400 // METRICS_STRIDE_S

    if dry_run:
        print(f"DRY RUN — {days}-day window: {start_t.date()} → {end_t.date()}", flush=True)
        print(
            f"Sampling: logs stride={LOGS_STRIDE_S}s ({ticks_log} ticks/source), "
            f"metrics stride={METRICS_STRIDE_S}s ({ticks_met} ticks), "
            f"chunk={BULK_CHUNK}",
            flush=True,
        )
        print("Idempotency: delete_by_query before writing (all streams)", flush=True)
    else:
        print(
            f"Backfill {days} days: {start_t.isoformat()} → {end_t.isoformat()}",
            flush=True,
        )

    totals: dict[str, int] = {}
    do_logs = sources in ("all", "logs")
    do_metrics = sources in ("all", "metrics")

    if do_logs:
        for src_name, stream, gen_fn in _LOG_SOURCES:
            n = _backfill_log_source(
                ctx, topo, src_name, stream, gen_fn, start_t, end_t, dry_run
            )
            totals[stream] = n

    if do_metrics:
        totals["logs-netflow.log-default"] = _backfill_netflow(
            ctx, topo, start_t, end_t, dry_run
        )
        totals["metrics-snmp.device-default"] = _backfill_snmp(
            ctx, topo, start_t, end_t, dry_run
        )

    total_docs = sum(totals.values())
    print(f"\nBackfill complete: {total_docs:,} total docs", flush=True)
    for stream, count in totals.items():
        print(f"  {stream}: {count:,}", flush=True)
    return totals


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Back-fill synthetic network data into Elasticsearch"
    )
    parser.add_argument(
        "--days",
        type=int,
        default=7,
        help="Number of days to back-fill (default: 7)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print planned volumes without writing to ES",
    )
    parser.add_argument(
        "--sources",
        choices=["all", "logs", "metrics"],
        default="all",
        help="Which sources to back-fill (default: all)",
    )
    args = parser.parse_args()

    if args.dry_run:
        ctx = Ctx(
            es_url=os.environ.get("ES_URL", "http://localhost:9200"),
            kibana_url=os.environ.get("KIBANA_URL", "http://localhost:5601"),
            api_key=os.environ.get("ELASTIC_API_KEY", ""),
        )
    else:
        es_url = os.environ.get("ES_URL", "")
        api_key = os.environ.get("ELASTIC_API_KEY", "")
        if not (es_url and api_key):
            print(
                "ERROR: ES_URL and ELASTIC_API_KEY must be set",
                file=sys.stderr,
            )
            sys.exit(1)
        ctx = Ctx(
            es_url=es_url,
            kibana_url=os.environ.get("KIBANA_URL", ""),
            api_key=api_key,
        )

    run_backfill(ctx, days=args.days, sources=args.sources, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
