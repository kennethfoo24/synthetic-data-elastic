"""NetFlow v9 flow-record generator (pure — no I/O, no side effects).

Decision: one exporter (the generator pod) rather than per-device exporters.
Per-device exporters are deferred to the MCP-app plan. The flow matrix is built
from source.ip / destination.ip fields in each data record, which are correct
regardless of which exporter sent the packet.
"""

from __future__ import annotations

import random
from datetime import datetime

from synthgen import GLOBAL_SEED
from synthgen.common.patterns import in_backup_window, rate_multiplier
from synthgen.common.topology import Topology
from synthgen.netflow_gen.encoder import FlowRecord


def generate_records(
    topo: Topology, t: datetime, seed: int = GLOBAL_SEED
) -> list[FlowRecord]:
    """Generate NetFlow v9 data records for one 1-second tick (pure function).

    For each flow in the topology two records are emitted:
      - forward (src→dst): baseline_bps × rate_multiplier bytes/interval
      - reverse (dst→src): ~10 % of forward bytes (typical ACK/response traffic)

    Backup-class flows are gated by the backup window overlay:
      × 20 inside in_backup_window(t), × 0.05 outside.

    FIRST_SWITCHED / LAST_SWITCHED are sysUptime-relative millisecond values
    derived deterministically from t, spanning a ~900 ms window within the tick.
    """
    if t.tzinfo is None:
        raise ValueError("t must be timezone-aware")

    # sysUptime wraps at 2^32 ms (≈ 49.7 days); treat unix timestamp ms as proxy.
    sys_uptime_ms = int(t.timestamp() * 1000) & 0xFFFFFFFF
    first_sw = (sys_uptime_ms - 950) & 0xFFFFFFFF   # flow started 950 ms ago
    last_sw = (sys_uptime_ms - 50) & 0xFFFFFFFF     # flow ended 50 ms ago

    minute_bucket = int(t.timestamp()) // 60
    records: list[FlowRecord] = []

    for flow in topo.flows:
        src_dev = topo.device(flow.src)
        dst_dev = topo.device(flow.dst)

        mult = rate_multiplier(t, flow.flow_class, flow.name, seed)
        if flow.flow_class == "backup":
            mult *= 20 if in_backup_window(t) else 0.05

        interval_bytes = max(1, int(flow.baseline_bps * mult / 8))
        pkts = max(1, interval_bytes // 800)

        # Ephemeral source port: deterministic within each minute bucket per flow
        rng = random.Random(f"{seed}|{flow.name}|{minute_bucket}")
        src_port = rng.randint(1024, 65000)

        proto = 6 if flow.proto == "tcp" else 17

        # Forward flow (src → dst)
        records.append(FlowRecord(
            src_addr=src_dev.ip,
            dst_addr=dst_dev.ip,
            src_port=src_port,
            dst_port=flow.dst_port,
            protocol=proto,
            in_bytes=interval_bytes,
            in_pkts=pkts,
            first_switched=first_sw,
            last_switched=last_sw,
        ))

        # Reverse / response flow (~10 % bytes, ports swapped)
        rev_bytes = max(1, interval_bytes // 10)
        rev_pkts = max(1, rev_bytes // 800)
        records.append(FlowRecord(
            src_addr=dst_dev.ip,
            dst_addr=src_dev.ip,
            src_port=flow.dst_port,
            dst_port=src_port,
            protocol=proto,
            in_bytes=rev_bytes,
            in_pkts=rev_pkts,
            first_switched=first_sw,
            last_switched=last_sw,
        ))

    return records
