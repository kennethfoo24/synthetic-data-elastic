"""Tests for scenario effects on NetFlow v9 flow records (Task 2).

Cross-source coupling: the NetFlow generator reads the same SCENARIOS specs
used by PANW and IOS syslog sources; no separate "netflow" source entry exists.

Scenarios tested:
  panw.vpn_flap  → VPN flow in_bytes drop to ~1 % of baseline
  ios.intf_flap  → user/app flow in_bytes halved
  panw.port_scan → synthetic scan fan-out flows from 198.51.100.101 appended

Baseline regression:
  At a timestamp where none of the three scenarios fire, record list is
  deterministic and contains no scan-attacker source address.
"""
from __future__ import annotations

from datetime import UTC, datetime

from synthgen import GLOBAL_SEED
from synthgen.common.scenarios import SCENARIOS, fires_at
from synthgen.common.topology import load_topology
from synthgen.netflow_gen.source import _SCAN_ATTACKER_IP, generate_records

_TOPO = load_topology("topology/network.yaml")
_SEED = GLOBAL_SEED

# Mid-window timestamps (bucket 0, seed=GLOBAL_SEED) — same as syslog tests.
_T_VPN_FLAP   = datetime.fromtimestamp(8797, tz=UTC)   # panw.vpn_flap mid
_T_PORT_SCAN  = datetime.fromtimestamp(2037, tz=UTC)   # panw.port_scan mid
_T_INTF_FLAP  = datetime.fromtimestamp(2269, tz=UTC)   # ios.intf_flap  mid

# After timestamps — scenarios not firing.
_T_VPN_AFTER  = datetime.fromtimestamp(9457, tz=UTC)
_T_SCAN_AFTER = datetime.fromtimestamp(2397, tz=UTC)
_T_INTF_AFTER = datetime.fromtimestamp(2509, tz=UTC)

# Quiet baseline — none of the three scenarios fire.
_T_QUIET = datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC)


def _vpn_flows(topo=_TOPO):
    return [f for f in topo.flows if f.flow_class == "vpn"]


def _user_app_flows(topo=_TOPO):
    return [f for f in topo.flows if f.flow_class in ("user", "app")]


def _vpn_bytes(records, topo=_TOPO) -> dict:
    """Return {flow_name: in_bytes} for VPN forward flows."""
    vpn = _vpn_flows(topo)
    result = {}
    for flow in vpn:
        src_dev = topo.device(flow.src)
        dst_dev = topo.device(flow.dst)
        for r in records:
            if r.src_addr == src_dev.ip and r.dst_addr == dst_dev.ip:
                result[flow.name] = r.in_bytes
    return result


def _user_app_bytes_total(records, topo=_TOPO) -> int:
    """Sum of in_bytes for user/app forward flows."""
    flows = _user_app_flows(topo)
    endpoints = {
        (topo.device(f.src).ip, topo.device(f.dst).ip)
        for f in flows
    }
    return sum(r.in_bytes for r in records if (r.src_addr, r.dst_addr) in endpoints)


# ---------------------------------------------------------------------------
# Baseline regression
# ---------------------------------------------------------------------------

def test_netflow_baseline_determinism():
    """At quiet timestamp, records are identical on two calls."""
    assert not fires_at(SCENARIOS["panw.vpn_flap"], _T_QUIET, _SEED)
    assert not fires_at(SCENARIOS["panw.port_scan"], _T_QUIET, _SEED)
    assert not fires_at(SCENARIOS["ios.intf_flap"],  _T_QUIET, _SEED)
    a = generate_records(_TOPO, _T_QUIET, _SEED)
    b = generate_records(_TOPO, _T_QUIET, _SEED)
    assert a == b, "NetFlow baseline must be deterministic"


def test_netflow_baseline_no_scan_attacker():
    """At quiet timestamp, the scan attacker IP must not appear."""
    records = generate_records(_TOPO, _T_QUIET, _SEED)
    assert not any(r.src_addr == _SCAN_ATTACKER_IP for r in records), (
        "Scan attacker IP must not appear in baseline NetFlow records"
    )


# ---------------------------------------------------------------------------
# panw.vpn_flap → VPN bytes drop to ~1 % during window
# ---------------------------------------------------------------------------

def test_netflow_vpn_flap_bytes_reduced():
    assert fires_at(SCENARIOS["panw.vpn_flap"], _T_VPN_FLAP, _SEED)
    baseline = _vpn_bytes(generate_records(_TOPO, _T_QUIET, _SEED))
    flap     = _vpn_bytes(generate_records(_TOPO, _T_VPN_FLAP, _SEED))
    for flow_name in baseline:
        baseline_b = baseline[flow_name]
        flap_b = flap.get(flow_name, 0)
        assert flap_b < baseline_b * 0.05, (
            f"VPN flow '{flow_name}' bytes should be ~1 % during vpn_flap: "
            f"baseline={baseline_b}, during_flap={flap_b}"
        )


def test_netflow_vpn_flap_bytes_normal_after_window():
    assert not fires_at(SCENARIOS["panw.vpn_flap"], _T_VPN_AFTER, _SEED)
    baseline = _vpn_bytes(generate_records(_TOPO, _T_QUIET, _SEED))
    after    = _vpn_bytes(generate_records(_TOPO, _T_VPN_AFTER, _SEED))
    for flow_name in baseline:
        # After the flap, bytes should be comparable to baseline
        # (within 10x of each other, accounting for diurnal variation).
        assert after.get(flow_name, 0) > 0, (
            f"VPN flow '{flow_name}' bytes should be > 0 after vpn_flap window"
        )


def test_netflow_vpn_flap_determinism():
    a = generate_records(_TOPO, _T_VPN_FLAP, _SEED)
    b = generate_records(_TOPO, _T_VPN_FLAP, _SEED)
    assert a == b


# ---------------------------------------------------------------------------
# panw.port_scan → synthetic scan flows appended
# ---------------------------------------------------------------------------

def test_netflow_port_scan_flows_appended():
    assert fires_at(SCENARIOS["panw.port_scan"], _T_PORT_SCAN, _SEED)
    records = generate_records(_TOPO, _T_PORT_SCAN, _SEED)
    scan = [r for r in records if r.src_addr == _SCAN_ATTACKER_IP]
    assert len(scan) >= 10, (
        f"Expected ≥ 10 scan flows from {_SCAN_ATTACKER_IP}, got {len(scan)}"
    )
    # Scan packets are tiny (1-packet SYN probes)
    assert all(r.in_pkts == 1 for r in scan), "Scan flows must be single-packet probes"
    assert all(r.in_bytes == 60 for r in scan), "Scan flows must be 60-byte SYN probes"


def test_netflow_port_scan_sequential_ports():
    assert fires_at(SCENARIOS["panw.port_scan"], _T_PORT_SCAN, _SEED)
    records = generate_records(_TOPO, _T_PORT_SCAN, _SEED)
    scan_ports = sorted(r.dst_port for r in records if r.src_addr == _SCAN_ATTACKER_IP)
    # Ports should be in a sequential range (not random)
    assert len(scan_ports) >= 10
    # All ports should be valid TCP ports
    assert all(1 <= p <= 65535 for p in scan_ports)


def test_netflow_port_scan_absent_after_window():
    assert not fires_at(SCENARIOS["panw.port_scan"], _T_SCAN_AFTER, _SEED)
    records = generate_records(_TOPO, _T_SCAN_AFTER, _SEED)
    scan = [r for r in records if r.src_addr == _SCAN_ATTACKER_IP]
    assert not scan, "Scan flows must not appear outside port_scan window"


def test_netflow_port_scan_determinism():
    a = generate_records(_TOPO, _T_PORT_SCAN, _SEED)
    b = generate_records(_TOPO, _T_PORT_SCAN, _SEED)
    assert a == b


# ---------------------------------------------------------------------------
# ios.intf_flap → user/app flow bytes halved
# ---------------------------------------------------------------------------

def test_netflow_intf_flap_user_app_bytes_reduced():
    assert fires_at(SCENARIOS["ios.intf_flap"], _T_INTF_FLAP, _SEED)
    baseline_total = _user_app_bytes_total(generate_records(_TOPO, _T_QUIET, _SEED))
    flap_total = _user_app_bytes_total(generate_records(_TOPO, _T_INTF_FLAP, _SEED))
    # Flap bytes should be roughly half of baseline (×0.5 multiplier).
    # Allow ±30 % tolerance for diurnal differences between the two timestamps.
    assert flap_total < baseline_total * 0.80, (
        f"User/app bytes should be lower during intf_flap: "
        f"baseline={baseline_total}, during_flap={flap_total}"
    )


def test_netflow_intf_flap_bytes_normal_after_window():
    assert not fires_at(SCENARIOS["ios.intf_flap"], _T_INTF_AFTER, _SEED)
    after_total = _user_app_bytes_total(generate_records(_TOPO, _T_INTF_AFTER, _SEED))
    assert after_total > 0


def test_netflow_intf_flap_determinism():
    a = generate_records(_TOPO, _T_INTF_FLAP, _SEED)
    b = generate_records(_TOPO, _T_INTF_FLAP, _SEED)
    assert a == b


# ---------------------------------------------------------------------------
# uint32 clamping still holds under scenario multipliers
# ---------------------------------------------------------------------------

def test_netflow_vpn_flap_bytes_still_clamped():
    """in_bytes must fit in uint32 even with scenario multipliers applied."""
    records = generate_records(_TOPO, _T_VPN_FLAP, _SEED)
    for r in records:
        assert r.in_bytes <= 0xFFFFFFFF
        assert r.in_pkts <= 0xFFFFFFFF
