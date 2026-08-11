"""Tests for scenario effects layered on syslog sources (Task 2).

Per-scenario assertions:
  - Marker messages appear inside the firing window
  - Marker messages are absent at the known no-scenario timestamp
  - Determinism: identical (topo, t, seed) → identical output

Baseline regression (4 tests, one per syslog source):
  - At datetime(2026, 1, 1, 0, 0, 0, UTC) no scenarios fire for any syslog source.
  - Output is deterministic and contains no scenario-specific markers.

Firing timestamps are derived from _firing_start_epoch(spec, bucket=0, seed=GLOBAL_SEED)
and verified offline; the source of truth is the scenarios module itself.
"""
from __future__ import annotations

from datetime import UTC, datetime

from synthgen import GLOBAL_SEED
from synthgen.common.scenarios import SCENARIOS, active_scenarios
from synthgen.common.topology import load_topology
from synthgen.syslog_gen import asa_source, ios_source, meraki_source, panw_source

_TOPO = load_topology("topology/network.yaml")
_SEED = GLOBAL_SEED

# A timestamp where NO scenario fires for any syslog source (verified computationally).
_T_QUIET = datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC)

# Mid-window timestamps for each scenario (bucket 0, seed=GLOBAL_SEED).
# Each is start_ep + duration_s // 2 and satisfies fires_at(spec, t, seed).
_T = {
    "panw.port_scan":    datetime.fromtimestamp(2037, tz=UTC),   # elapsed=300s
    "panw.malware_detect": datetime.fromtimestamp(6954, tz=UTC), # elapsed=900s
    "panw.vpn_flap":     datetime.fromtimestamp(8797, tz=UTC),   # elapsed=600s
    "asa.brute_force":   datetime.fromtimestamp(6066, tz=UTC),   # elapsed=150s
    "asa.conn_storm":    datetime.fromtimestamp(8434, tz=UTC),   # elapsed=225s
    "asa.failover":      datetime.fromtimestamp(1917, tz=UTC),   # elapsed=750s
    "ios.intf_flap":     datetime.fromtimestamp(2269, tz=UTC),   # elapsed=180s  (180%30==0)
    "ios.stp_reconverge": datetime.fromtimestamp(2847, tz=UTC),  # elapsed=150s  (150%15==0)
    "ios.cpu_spike":     datetime.fromtimestamp(8184, tz=UTC),   # elapsed=600s
    "meraki.ap_offline": datetime.fromtimestamp(4217, tz=UTC),   # elapsed=450s
    "meraki.rogue_ap":   datetime.fromtimestamp(3388, tz=UTC),   # elapsed=360s
    "meraki.wan_failover": datetime.fromtimestamp(2073, tz=UTC), # elapsed=900s
}

# 60 s after window end — verified not firing.
_T_AFTER = {
    "panw.port_scan":    datetime.fromtimestamp(2397, tz=UTC),
    "panw.malware_detect": datetime.fromtimestamp(7914, tz=UTC),
    "panw.vpn_flap":     datetime.fromtimestamp(9457, tz=UTC),
    "asa.brute_force":   datetime.fromtimestamp(6276, tz=UTC),
    "asa.conn_storm":    datetime.fromtimestamp(9019, tz=UTC),
    "asa.failover":      datetime.fromtimestamp(2727, tz=UTC),
    "ios.intf_flap":     datetime.fromtimestamp(2509, tz=UTC),
    "ios.stp_reconverge": datetime.fromtimestamp(3057, tz=UTC),
    "ios.cpu_spike":     datetime.fromtimestamp(9744, tz=UTC),
    "meraki.ap_offline": datetime.fromtimestamp(5147, tz=UTC),
    "meraki.rogue_ap":   datetime.fromtimestamp(4108, tz=UTC),
    "meraki.wan_failover": datetime.fromtimestamp(3933, tz=UTC),
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _batch(source: str, t: datetime) -> list[str]:
    if source == "panw":
        return panw_source.generate_batch(_TOPO, t, _SEED)
    if source == "asa":
        return asa_source.generate_batch(_TOPO, t, _SEED)
    if source == "ios":
        return ios_source.generate_batch(_TOPO, t, _SEED)
    if source == "meraki":
        return meraki_source.generate_batch(_TOPO, t, _SEED)
    raise ValueError(source)


def _joined(lines: list[str]) -> str:
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Baseline regression — byte-identical when no scenarios are active
# ---------------------------------------------------------------------------

def test_asa_baseline_no_scenario_regression():
    """At quiet timestamp, ASA output is deterministic and free of scenario markers."""
    assert active_scenarios("asa", _T_QUIET, _SEED) == [], "Expected no active ASA scenarios"
    a = asa_source.generate_batch(_TOPO, _T_QUIET, _SEED)
    b = asa_source.generate_batch(_TOPO, _T_QUIET, _SEED)
    assert a == b, "ASA baseline output must be deterministic"
    text = _joined(a)
    assert "198.51.100." not in text, "Scenario attacker IP must not appear in baseline"
    assert "104001" not in text, "Failover-active message must not appear in baseline"
    assert "104002" not in text, "Failover-standby message must not appear in baseline"


def test_ios_baseline_no_scenario_regression():
    """At quiet timestamp, IOS output is deterministic and free of scenario markers."""
    assert active_scenarios("ios", _T_QUIET, _SEED) == [], "Expected no active IOS scenarios"
    a = ios_source.generate_batch(_TOPO, _T_QUIET, _SEED)
    b = ios_source.generate_batch(_TOPO, _T_QUIET, _SEED)
    assert a == b, "IOS baseline output must be deterministic"
    text = _joined(a)
    assert "TOPOLOGY_CHANGE" not in text, "STP topology-change must not appear in baseline"
    assert "PORTSTATUS" not in text, "STP port-status must not appear in baseline"
    assert "CPUHOG" not in text, "CPU-hog must not appear in baseline"


def test_panw_baseline_no_scenario_regression():
    """At quiet timestamp, PANW output is deterministic and free of scenario markers."""
    assert active_scenarios("panw", _T_QUIET, _SEED) == [], "Expected no active PANW scenarios"
    a = panw_source.generate_batch(_TOPO, _T_QUIET, _SEED)
    b = panw_source.generate_batch(_TOPO, _T_QUIET, _SEED)
    assert a == b, "PANW baseline output must be deterministic"
    text = _joined(a)
    assert "tunnel-down" not in text, "VPN tunnel-down must not appear in baseline"
    assert "198.51.100." not in text, "Scenario IP must not appear in baseline PANW output"


def test_meraki_baseline_no_scenario_regression():
    """At quiet timestamp, Meraki output is deterministic and free of scenario markers."""
    assert active_scenarios("meraki", _T_QUIET, _SEED) == [], "Expected no active Meraki scenarios"
    a = meraki_source.generate_batch(_TOPO, _T_QUIET, _SEED)
    b = meraki_source.generate_batch(_TOPO, _T_QUIET, _SEED)
    assert a == b, "Meraki baseline output must be deterministic"
    text = _joined(a)
    assert "device_down" not in text, "device_down must not appear in baseline"
    assert "device_up" not in text, "device_up must not appear in baseline"
    assert "air_marshal_detected" not in text, "Air Marshal must not appear in baseline"
    assert "uplink_change" not in text, "uplink_change must not appear in baseline"


# ---------------------------------------------------------------------------
# ASA scenarios
# ---------------------------------------------------------------------------

def test_asa_brute_force_marker_inside_window():
    lines = asa_source.generate_batch(_TOPO, _T["asa.brute_force"], _SEED)
    text = _joined(lines)
    assert "198.51.100." in text, "Scenario brute-force attacker IP must appear inside window"
    # Verify it's an auth-failure message
    assert any("198.51.100." in l and "113005" in l for l in lines), (
        "Expected 113005 auth-failure from 198.51.100.x inside brute_force window"
    )


def test_asa_brute_force_absent_outside_window():
    lines = asa_source.generate_batch(_TOPO, _T_AFTER["asa.brute_force"], _SEED)
    text = _joined(lines)
    assert "198.51.100." not in text, "Scenario attacker IP must not appear outside window"


def test_asa_brute_force_determinism():
    t = _T["asa.brute_force"]
    assert asa_source.generate_batch(_TOPO, t, _SEED) == asa_source.generate_batch(_TOPO, t, _SEED)


def test_asa_conn_storm_marker_inside_window():
    lines = asa_source.generate_batch(_TOPO, _T["asa.conn_storm"], _SEED)
    text = _joined(lines)
    assert "198.51.100." in text, "Storm attacker IP must appear inside conn_storm window"
    assert any("198.51.100." in l and ("302013" in l or "302014" in l or "106023" in l)
               for l in lines), "Expected connection records from 198.51.100.x"


def test_asa_conn_storm_absent_outside_window():
    lines = asa_source.generate_batch(_TOPO, _T_AFTER["asa.conn_storm"], _SEED)
    assert "198.51.100." not in _joined(lines)


def test_asa_conn_storm_determinism():
    t = _T["asa.conn_storm"]
    assert asa_source.generate_batch(_TOPO, t, _SEED) == asa_source.generate_batch(_TOPO, t, _SEED)


def test_asa_failover_marker_inside_window():
    lines = asa_source.generate_batch(_TOPO, _T["asa.failover"], _SEED)
    # Mid-window (elapsed=750s, remaining=750s > 150s) → 104001 messages
    assert any("104001" in l for l in lines), (
        "Expected ASA-1-104001 failover message inside window"
    )


def test_asa_failover_absent_outside_window():
    lines = asa_source.generate_batch(_TOPO, _T_AFTER["asa.failover"], _SEED)
    text = _joined(lines)
    assert "104001" not in text and "104002" not in text, (
        "Failover messages must not appear outside window"
    )


def test_asa_failover_determinism():
    t = _T["asa.failover"]
    assert asa_source.generate_batch(_TOPO, t, _SEED) == asa_source.generate_batch(_TOPO, t, _SEED)


# ---------------------------------------------------------------------------
# IOS scenarios
# ---------------------------------------------------------------------------

def test_ios_intf_flap_marker_inside_window():
    # elapsed=180s, 180%30==0 → link flap emitted
    lines = ios_source.generate_batch(_TOPO, _T["ios.intf_flap"], _SEED)
    link_lines = [l for l in lines if "LINK-3-UPDOWN" in l]
    proto_lines = [l for l in lines if "LINEPROTO-5-UPDOWN" in l]
    assert link_lines, "Expected LINK-3-UPDOWN from ios.intf_flap inside window"
    assert proto_lines, "Expected LINEPROTO-5-UPDOWN from ios.intf_flap inside window"


def test_ios_intf_flap_absent_outside_window():
    # The "after" timestamp is 2509 (60 s after window end).  At that point,
    # elapsed%30 will generally not be 0, but the scenario also won't be active.
    lines = ios_source.generate_batch(_TOPO, _T_AFTER["ios.intf_flap"], _SEED)
    # Only baseline link-updown lines can appear (very rare, ~1% probability).
    # The scenario adds them with a FIXED interface; baseline uses random ones.
    # We verify the scenario-seeded interface doesn't dominate the output.
    import random
    iface_rng = random.Random(f"{_SEED}|ios.intf_flap|cisco-rtr-core-01|iface")
    sc_iface = f"GigabitEthernet{iface_rng.randint(0,1)}/{iface_rng.randint(1,3)}"
    # Scenario should NOT fire, so no line from the fixed flap interface at that time.
    assert active_scenarios("ios", _T_AFTER["ios.intf_flap"], _SEED) == []
    sc_link_lines = [l for l in lines if "LINK-3-UPDOWN" in l and sc_iface in l]
    assert not sc_link_lines, "Scenario LINK-3-UPDOWN must not appear outside window"


def test_ios_intf_flap_determinism():
    t = _T["ios.intf_flap"]
    assert ios_source.generate_batch(_TOPO, t, _SEED) == ios_source.generate_batch(_TOPO, t, _SEED)


def test_ios_stp_reconverge_marker_inside_window():
    # elapsed=150s, 150%15==0 → STP messages emitted
    lines = ios_source.generate_batch(_TOPO, _T["ios.stp_reconverge"], _SEED)
    assert any("TOPOLOGY_CHANGE" in l for l in lines), (
        "Expected SPANTREE-2-TOPOLOGY_CHANGE inside ios.stp_reconverge window"
    )
    assert any("PORTSTATUS" in l for l in lines), (
        "Expected SPANTREE-7-PORTSTATUS inside ios.stp_reconverge window"
    )


def test_ios_stp_reconverge_absent_outside_window():
    assert active_scenarios("ios", _T_AFTER["ios.stp_reconverge"], _SEED) == []
    lines = ios_source.generate_batch(_TOPO, _T_AFTER["ios.stp_reconverge"], _SEED)
    assert not any("TOPOLOGY_CHANGE" in l for l in lines)
    assert not any("PORTSTATUS" in l for l in lines)


def test_ios_stp_reconverge_determinism():
    t = _T["ios.stp_reconverge"]
    assert ios_source.generate_batch(_TOPO, t, _SEED) == ios_source.generate_batch(_TOPO, t, _SEED)


def test_ios_cpu_spike_marker_inside_window():
    lines = ios_source.generate_batch(_TOPO, _T["ios.cpu_spike"], _SEED)
    assert any("CPUHOG" in l for l in lines), (
        "Expected SYS-3-CPUHOG inside ios.cpu_spike window"
    )
    # CPU % should be elevated (> 70)
    cpuhog_lines = [l for l in lines if "CPUHOG" in l]
    assert any("CPU utilization" in l for l in cpuhog_lines)


def test_ios_cpu_spike_absent_outside_window():
    assert active_scenarios("ios", _T_AFTER["ios.cpu_spike"], _SEED) == []
    lines = ios_source.generate_batch(_TOPO, _T_AFTER["ios.cpu_spike"], _SEED)
    assert not any("CPUHOG" in l for l in lines)


def test_ios_cpu_spike_determinism():
    t = _T["ios.cpu_spike"]
    assert ios_source.generate_batch(_TOPO, t, _SEED) == ios_source.generate_batch(_TOPO, t, _SEED)


# ---------------------------------------------------------------------------
# PANW scenarios
# ---------------------------------------------------------------------------

def test_panw_port_scan_marker_inside_window():
    lines = panw_source.generate_batch(_TOPO, _T["panw.port_scan"], _SEED)
    text = _joined(lines)
    assert "198.51.100." in text, (
        "Scan attacker IP (198.51.100.x) must appear in PANW output during port_scan"
    )
    # Scenario THREATs are distinctly from the scan net
    threat_from_scan = [l for l in lines if "THREAT" in l and "198.51.100." in l]
    assert len(threat_from_scan) >= 5, (
        f"Expected ≥ 5 scan THREATs inside window, got {len(threat_from_scan)}"
    )


def test_panw_port_scan_absent_outside_window():
    assert active_scenarios("panw", _T_AFTER["panw.port_scan"], _SEED) == []
    lines = panw_source.generate_batch(_TOPO, _T_AFTER["panw.port_scan"], _SEED)
    assert "198.51.100." not in _joined(lines)


def test_panw_port_scan_determinism():
    t = _T["panw.port_scan"]
    assert panw_source.generate_batch(_TOPO, t, _SEED) == panw_source.generate_batch(_TOPO, t, _SEED)


def test_panw_malware_detect_marker_inside_window():
    lines = panw_source.generate_batch(_TOPO, _T["panw.malware_detect"], _SEED)
    # C2 IP is in 198.51.100.201-250 range; src is internal server.
    spyware_lines = [l for l in lines if "THREAT" in l and "spyware" in l and "198.51.100." in l]
    assert spyware_lines, "Expected spyware THREAT with C2 IP inside malware_detect window"


def test_panw_malware_detect_absent_outside_window():
    assert active_scenarios("panw", _T_AFTER["panw.malware_detect"], _SEED) == []
    lines = panw_source.generate_batch(_TOPO, _T_AFTER["panw.malware_detect"], _SEED)
    assert "198.51.100." not in _joined(lines)


def test_panw_malware_detect_determinism():
    t = _T["panw.malware_detect"]
    assert panw_source.generate_batch(_TOPO, t, _SEED) == panw_source.generate_batch(_TOPO, t, _SEED)


def test_panw_vpn_flap_marker_inside_window():
    lines = panw_source.generate_batch(_TOPO, _T["panw.vpn_flap"], _SEED)
    # Mid-window (elapsed=600s, remaining=600s > 120s) → tunnel-down SYSTEM
    assert any("tunnel-down" in l for l in lines), (
        "Expected VPN tunnel-down SYSTEM event inside panw.vpn_flap window"
    )
    assert any("SYSTEM" in l and "vpn" in l for l in lines), (
        "Expected SYSTEM log with vpn subtype inside panw.vpn_flap window"
    )


def test_panw_vpn_flap_absent_outside_window():
    assert active_scenarios("panw", _T_AFTER["panw.vpn_flap"], _SEED) == []
    lines = panw_source.generate_batch(_TOPO, _T_AFTER["panw.vpn_flap"], _SEED)
    assert not any("tunnel-down" in l for l in lines)
    assert not any("tunnel-up" in l for l in lines)


def test_panw_vpn_flap_determinism():
    t = _T["panw.vpn_flap"]
    assert panw_source.generate_batch(_TOPO, t, _SEED) == panw_source.generate_batch(_TOPO, t, _SEED)


# ---------------------------------------------------------------------------
# Meraki scenarios
# ---------------------------------------------------------------------------

def test_meraki_ap_offline_marker_inside_window():
    lines = meraki_source.generate_batch(_TOPO, _T["meraki.ap_offline"], _SEED)
    assert any("device_down" in l for l in lines), (
        "Expected device_down event inside meraki.ap_offline window"
    )


def test_meraki_ap_offline_absent_outside_window():
    assert active_scenarios("meraki", _T_AFTER["meraki.ap_offline"], _SEED) == []
    lines = meraki_source.generate_batch(_TOPO, _T_AFTER["meraki.ap_offline"], _SEED)
    assert not any("device_down" in l for l in lines)
    assert not any("device_up" in l for l in lines)


def test_meraki_ap_offline_determinism():
    t = _T["meraki.ap_offline"]
    assert meraki_source.generate_batch(_TOPO, t, _SEED) == meraki_source.generate_batch(_TOPO, t, _SEED)


def test_meraki_rogue_ap_marker_inside_window():
    lines = meraki_source.generate_batch(_TOPO, _T["meraki.rogue_ap"], _SEED)
    assert any("air_marshal_detected" in l for l in lines), (
        "Expected air_marshal_detected event inside meraki.rogue_ap window"
    )
    assert any("FreePublicWiFi" in l for l in lines), (
        "Expected rogue SSID in Air Marshal event"
    )


def test_meraki_rogue_ap_absent_outside_window():
    # Verify rogue_ap specifically is not firing (other Meraki scenarios may overlap).
    from synthgen.common.scenarios import fires_at
    assert not fires_at(SCENARIOS["meraki.rogue_ap"], _T_AFTER["meraki.rogue_ap"], _SEED)
    lines = meraki_source.generate_batch(_TOPO, _T_AFTER["meraki.rogue_ap"], _SEED)
    assert not any("air_marshal_detected" in l for l in lines)


def test_meraki_rogue_ap_determinism():
    t = _T["meraki.rogue_ap"]
    assert meraki_source.generate_batch(_TOPO, t, _SEED) == meraki_source.generate_batch(_TOPO, t, _SEED)


def test_meraki_wan_failover_marker_inside_window():
    lines = meraki_source.generate_batch(_TOPO, _T["meraki.wan_failover"], _SEED)
    # Mid-window (elapsed=900s, remaining=900s > 180s) → wan2 failover
    assert any("uplink_change" in l for l in lines), (
        "Expected uplink_change event inside meraki.wan_failover window"
    )
    assert any("wan2" in l for l in lines), (
        "Expected wan2 to be active (failover) at mid-window"
    )


def test_meraki_wan_failover_absent_outside_window():
    # Verify wan_failover specifically is not firing (other Meraki scenarios may overlap).
    from synthgen.common.scenarios import fires_at
    assert not fires_at(SCENARIOS["meraki.wan_failover"], _T_AFTER["meraki.wan_failover"], _SEED)
    lines = meraki_source.generate_batch(_TOPO, _T_AFTER["meraki.wan_failover"], _SEED)
    assert not any("uplink_change" in l for l in lines)


def test_meraki_wan_failover_determinism():
    t = _T["meraki.wan_failover"]
    assert meraki_source.generate_batch(_TOPO, t, _SEED) == meraki_source.generate_batch(_TOPO, t, _SEED)
