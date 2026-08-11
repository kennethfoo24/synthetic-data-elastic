"""PAN-OS syslog generator for palo-fw-prod.

Emits TRAFFIC (subtype=end), THREAT, and SYSTEM records via UDP syslog,
matching the panw Elastic integration's CSV field expectations.

Only ``palo-fw-prod`` (vendor_os=panos) emits.  TRAFFIC records are derived
from cross-site (production→dr) topology flows + the VPN-inbound direction of
the site-vpn flow.  THREAT records are generated rarely (~1/min).  SYSTEM
records are emitted once every ~2 minutes, rotating through a small set of
operational event types.
"""
from __future__ import annotations

import random
from datetime import datetime

from synthgen import GLOBAL_SEED
from synthgen.common.patterns import rate_multiplier
from synthgen.common.scenarios import active_scenarios
from synthgen.common.topology import Flow, Topology
from synthgen.syslog_gen.formats import panw

_FW_NAME = "palo-fw-prod"
_SERIAL = "001901000001"

# Peak TRAFFIC records per second emitted by palo-fw-prod (all flows combined).
PEAK_TRAFFIC_PER_SEC = 4

# Probability of emitting a THREAT record each 1-second tick (~1/min at baseline).
_THREAT_PROB_PER_SEC = 1.0 / 60.0

_THREAT_IDS = ["36882", "34896", "40128", "57432", "92432"]
_THREAT_SUBTYPES = ["vulnerability", "spyware"]
_THREAT_SEVERITIES = ["high", "medium", "critical"]
_APPS_EGRESS = ["ssl", "web-browsing", "unknown-tcp", "quic"]
_APPS_VPN = ["ipsec", "ike"]

# SYSTEM events: (subtype, eventid, severity, description)
# Description must contain no commas (plain CSV, not quoted).
_SYSTEM_EVENTS = [
    ("general",  "general",      "informational", "System operational check passed"),
    ("general",  "auth-success", "informational", "Admin authentication succeeded"),
    ("config",   "general",      "informational", "Configuration committed to device"),
]

# Emit one SYSTEM record every 120 seconds (deterministic modulo check).
_SYSTEM_INTERVAL_S = 120

# Scenario port-scan attacker net (RFC 5737 TEST-NET-2 — distinct from EXTERNAL_NET).
_SCAN_NET = "198.51.100."


def _egress_flows(topo: Topology) -> list[Flow]:
    """Flows from production-site devices to DR-site devices (cross-firewall boundary)."""
    prod_names = {d.name for d in topo.devices if d.site == "production"}
    dr_names = {d.name for d in topo.devices if d.site == "dr"}
    return [f for f in topo.flows if f.src in prod_names and f.dst in dr_names]


def generate_batch(topo: Topology, t: datetime, seed: int = GLOBAL_SEED) -> list[str]:
    """Return syslog lines for one 1-second tick from palo-fw-prod."""
    fw = topo.device(_FW_NAME)
    egress = _egress_flows(topo)
    if not egress:
        return []

    rng = random.Random(f"{seed}|{_FW_NAME}|{int(t.timestamp())}")
    lines: list[str] = []

    per_flow_peak = PEAK_TRAFFIC_PER_SEC / len(egress)

    # ── Egress TRAFFIC records (inside → outside) ──────────────────────────
    for flow in egress:
        mult = rate_multiplier(t, flow.flow_class, f"panw:{flow.name}", seed)
        n = int(per_flow_peak * mult) + (
            1 if rng.random() < (per_flow_peak * mult) % 1 else 0
        )
        bps = int(flow.baseline_bps * mult)
        for _ in range(n):
            elapsed = rng.randint(5, 300)
            bytes_total = max(1, bps * elapsed // 8)
            bytes_sent = max(1, int(bytes_total * rng.uniform(0.3, 0.7)))
            bytes_recv = max(1, bytes_total - bytes_sent)
            src_dev = topo.device(flow.src)
            dst_dev = topo.device(flow.dst)
            app = rng.choice(_APPS_VPN if flow.flow_class == "vpn" else _APPS_EGRESS)
            lines.append(panw.panos_traffic(
                ts=t,
                hostname=fw.name,
                serial=_SERIAL,
                src_ip=src_dev.ip,
                dst_ip=dst_dev.ip,
                src_port=rng.randint(1024, 65000),
                dst_port=flow.dst_port,
                proto=flow.proto,
                bytes_total=bytes_total,
                bytes_sent=bytes_sent,
                bytes_received=bytes_recv,
                src_zone="inside",
                dst_zone="outside",
                app=app,
                session_id=rng.randint(10_000, 999_999),
                elapsed=elapsed,
                seq_no=rng.randint(100_000, 9_999_999),
            ))

    # ── VPN-inbound TRAFFIC records (outside → inside, site-vpn reverse) ───
    vpn_flows = [f for f in egress if f.flow_class == "vpn"]
    for flow in vpn_flows:
        mult = rate_multiplier(t, flow.flow_class, f"panw:{flow.name}:inbound", seed)
        n = int(per_flow_peak * mult) + (
            1 if rng.random() < (per_flow_peak * mult) % 1 else 0
        )
        bps = int(flow.baseline_bps * mult)
        for _ in range(n):
            elapsed = rng.randint(5, 300)
            bytes_total = max(1, bps * elapsed // 8)
            bytes_sent = max(1, int(bytes_total * rng.uniform(0.3, 0.7)))
            bytes_recv = max(1, bytes_total - bytes_sent)
            # Reverse: DR device is the source, palo-fw-prod is the destination
            src_dev = topo.device(flow.dst)
            dst_dev = topo.device(flow.src)
            lines.append(panw.panos_traffic(
                ts=t,
                hostname=fw.name,
                serial=_SERIAL,
                src_ip=src_dev.ip,
                dst_ip=dst_dev.ip,
                src_port=rng.randint(1024, 65000),
                dst_port=flow.dst_port,
                proto=flow.proto,
                bytes_total=bytes_total,
                bytes_sent=bytes_sent,
                bytes_received=bytes_recv,
                src_zone="outside",
                dst_zone="inside",
                app=rng.choice(_APPS_VPN),
                session_id=rng.randint(10_000, 999_999),
                elapsed=elapsed,
                seq_no=rng.randint(100_000, 9_999_999),
            ))

    # ── Sparse SYSTEM records (~1 every 2 minutes, deterministic) ───────────
    if int(t.timestamp()) % _SYSTEM_INTERVAL_S == 0:
        event = _SYSTEM_EVENTS[int(t.timestamp() // _SYSTEM_INTERVAL_S) % len(_SYSTEM_EVENTS)]
        lines.append(panw.panos_system(
            ts=t,
            hostname=fw.name,
            serial=_SERIAL,
            subtype=event[0],
            eventid=event[1],
            severity=event[2],
            description=event[3],
            seq_no=rng.randint(100_000, 9_999_999),
        ))

    # ── Rare THREAT records ─────────────────────────────────────────────────
    if rng.random() < _THREAT_PROB_PER_SEC:
        servers = [d for d in topo.devices if d.site == "production" and d.role == "server"]
        dst = rng.choice(servers) if servers else fw
        lines.append(panw.panos_threat(
            ts=t,
            hostname=fw.name,
            serial=_SERIAL,
            src_ip=f"203.0.113.{rng.randint(2, 254)}",
            dst_ip=dst.ip,
            src_port=rng.randint(1024, 65000),
            dst_port=443,
            proto="tcp",
            subtype=rng.choice(_THREAT_SUBTYPES),
            threat_id=rng.choice(_THREAT_IDS),
            severity=rng.choice(_THREAT_SEVERITIES),
            src_zone="outside",
            dst_zone="inside",
            app=rng.choice(["web-browsing", "ssl"]),
            session_id=rng.randint(10_000, 999_999),
            seq_no=rng.randint(100_000, 9_999_999),
        ))

    # ── Scenario overlay (separate RNG; does not touch baseline rng) ─────────
    sc = active_scenarios("panw", t, seed)
    if sc:
        sc_rng = random.Random(f"{seed}|panw|sc|{int(t.timestamp())}")
        servers = [d for d in topo.devices if d.site == "production" and d.role == "server"]

        for spec, ph in sc:
            elapsed = ph * spec.duration_s

            if spec.id == "panw.port_scan":
                # Dense burst of THREAT/deny from one fixed external IP to sequential ports.
                scan_rng = random.Random(f"{seed}|{spec.id}|attacker")
                attacker_ip = _SCAN_NET + str(scan_rng.randint(100, 200))
                dst = servers[0] if servers else fw
                n_scan = max(5, int(20 * (1.0 - ph * 0.5)))
                port_offset = int(elapsed) * 20
                for i in range(n_scan):
                    dst_port = 1 + (port_offset + i) % 65534
                    lines.append(panw.panos_threat(
                        ts=t, hostname=fw.name, serial=_SERIAL,
                        src_ip=attacker_ip, dst_ip=dst.ip,
                        src_port=sc_rng.randint(1024, 65000),
                        dst_port=dst_port,
                        proto="tcp",
                        subtype="vulnerability",
                        threat_id="36882",
                        severity="high",
                        src_zone="outside", dst_zone="inside",
                        app="web-browsing",
                        session_id=sc_rng.randint(10_000, 999_999),
                        seq_no=sc_rng.randint(100_000, 9_999_999),
                    ))

            elif spec.id == "panw.malware_detect":
                # Spyware/C2 THREAT records: infected host reaches out to attacker IP.
                malware_rng = random.Random(f"{seed}|{spec.id}|c2")
                c2_ip = _SCAN_NET + str(malware_rng.randint(201, 250))
                victim = servers[int(len(servers) * ph) % len(servers)] if servers else fw
                n_detect = max(1, int(5 * min(ph, 1.0 - ph) * 2))  # tent function
                for _ in range(n_detect):
                    lines.append(panw.panos_threat(
                        ts=t, hostname=fw.name, serial=_SERIAL,
                        src_ip=victim.ip, dst_ip=c2_ip,
                        src_port=sc_rng.randint(1024, 65000),
                        dst_port=sc_rng.choice([443, 80, 8080]),
                        proto="tcp",
                        subtype="spyware",
                        threat_id=sc_rng.choice(["57432", "92432"]),
                        severity="critical",
                        src_zone="inside", dst_zone="outside",
                        app="ssl",
                        session_id=sc_rng.randint(10_000, 999_999),
                        seq_no=sc_rng.randint(100_000, 9_999_999),
                    ))

            elif spec.id == "panw.vpn_flap":
                # SYSTEM vpn tunnel-down during window; tunnel-up near end.
                remaining = spec.duration_s - elapsed
                if remaining > spec.duration_s * 0.1:
                    eventid = "tunnel-down"
                    severity = "high"
                    desc = "IPSec tunnel to DR site dropped - IKE timeout"
                else:
                    eventid = "tunnel-up"
                    severity = "informational"
                    desc = "IPSec tunnel to DR site re-established"
                lines.append(panw.panos_system(
                    ts=t, hostname=fw.name, serial=_SERIAL,
                    subtype="vpn",
                    eventid=eventid,
                    severity=severity,
                    description=desc,
                    seq_no=sc_rng.randint(100_000, 9_999_999),
                ))

    return lines
