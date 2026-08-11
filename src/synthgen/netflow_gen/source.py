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
from synthgen.common.scenarios import SCENARIOS, fires_at
from synthgen.common.scenarios import phase as sc_phase
from synthgen.common.topology import Topology
from synthgen.netflow_gen.encoder import FlowRecord

# Fixed attacker IP for port-scan fan-out flows (RFC 5737 TEST-NET-2).
_SCAN_ATTACKER_IP = "198.51.100.101"


def generate_records(
    topo: Topology, t: datetime, seed: int = GLOBAL_SEED
) -> list[FlowRecord]:
    """Generate NetFlow v9 data records for one 1-second tick (pure function).

    For each flow in the topology two records are emitted:
      - forward (src→dst): baseline_bps × rate_multiplier bytes/interval
      - reverse (dst→src): ~10 % of forward bytes (typical ACK/response traffic)

    Backup-class flows are gated by the backup window overlay:
      × 20 inside in_backup_window(t), × 0.05 outside.

    Scenario effects (cross-source coupling — reads same SCENARIOS specs as syslog):
      panw.vpn_flap  → VPN flow bytes drop to ~1 % during active window.
      ios.intf_flap  → user/app flow bytes halved during active flap.
      panw.port_scan → synthetic scan fan-out flows appended after baseline records.

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

    # ── Evaluate active scenario multipliers (no RNG consumed here) ──────────
    vpn_flap_spec = SCENARIOS["panw.vpn_flap"]
    vpn_flap_active = fires_at(vpn_flap_spec, t, seed)
    vpn_flap_ph = sc_phase(vpn_flap_spec, t, seed) if vpn_flap_active else None

    intf_flap_spec = SCENARIOS["ios.intf_flap"]
    intf_flap_active = fires_at(intf_flap_spec, t, seed)

    port_scan_spec = SCENARIOS["panw.port_scan"]
    port_scan_active = fires_at(port_scan_spec, t, seed)
    port_scan_ph = sc_phase(port_scan_spec, t, seed) if port_scan_active else None

    for flow in topo.flows:
        src_dev = topo.device(flow.src)
        dst_dev = topo.device(flow.dst)

        mult = rate_multiplier(t, flow.flow_class, flow.name, seed)
        if flow.flow_class == "backup":
            mult *= 20 if in_backup_window(t) else 0.05

        # ── Scenario multipliers ─────────────────────────────────────────────
        if flow.flow_class == "vpn" and vpn_flap_active and vpn_flap_ph is not None:
            # VPN tunnel is down: traffic drops to ~1 % of normal.
            # Recovery in last 10 % of window (ph > 0.9).
            if vpn_flap_ph < 0.9:
                mult *= 0.01
        elif flow.flow_class in ("user", "app") and intf_flap_active:
            # Interface flapping: traffic disruption on user/app flows.
            mult *= 0.5

        interval_bytes = min(0xFFFFFFFF, max(1, int(flow.baseline_bps * mult / 8)))
        pkts = min(0xFFFFFFFF, max(1, interval_bytes // 800))

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
        rev_bytes = min(0xFFFFFFFF, max(1, interval_bytes // 10))
        rev_pkts = min(0xFFFFFFFF, max(1, rev_bytes // 800))
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

    # ── Port-scan fan-out: many small probe flows from one external IP ───────
    if port_scan_active and port_scan_ph is not None:
        scan_rng = random.Random(f"{seed}|port_scan|netflow|{int(t.timestamp())}")
        victims = [d for d in topo.devices if d.site == "production" and d.role == "server"]
        if victims:
            victim = victims[0]
            elapsed = int(port_scan_ph * port_scan_spec.duration_s)
            n_scan = max(10, int(50 * (1.0 - port_scan_ph * 0.5)))
            port_offset = elapsed * 20
            for i in range(n_scan):
                dst_port = 1 + (port_offset + i) % 65534
                records.append(FlowRecord(
                    src_addr=_SCAN_ATTACKER_IP,
                    dst_addr=victim.ip,
                    src_port=scan_rng.randint(1024, 65000),
                    dst_port=dst_port,
                    protocol=6,  # TCP
                    in_bytes=60,  # tiny SYN probe
                    in_pkts=1,
                    first_switched=first_sw,
                    last_switched=last_sw,
                ))

    return records
