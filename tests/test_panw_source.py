"""Unit tests for panw_source.generate_batch.

Assertions:
  - Batch is deterministic (same seed, same tick → identical list)
  - Peak hour emits more records than 3 AM
  - All records originate from palo-fw-prod
  - TRAFFIC records appear at peak
  - Zone assignments are present in TRAFFIC records
  - THREAT records are rarer than TRAFFIC records over a sample window
"""
from __future__ import annotations

import re
from datetime import UTC, datetime

from synthgen.common.topology import load_topology
from synthgen.syslog_gen import panw_source


def _traffic_csv_fields(msg: str) -> list[str] | None:
    """Return CSV fields from a PAN-OS TRAFFIC syslog line, or None if not parseable."""
    if "TRAFFIC" not in msg:
        return None
    # Header: <14>Aug 11 12:00:00 palo-fw-prod csv...
    match = re.match(r"^<\d+>\w{3}\s+\d{1,2} \d{2}:\d{2}:\d{2} \S+ (.+)$", msg)
    if not match:
        return None
    return match.group(1).split(",")

_TOPO_PATH = "topology/network.yaml"
_SEED = 42

# Peak = hour 12 UTC (diurnal multiplier = 1.0); night = hour 3 UTC (mult ≈ 0.20)
_PEAK = datetime(2026, 8, 11, 12, 0, 0, tzinfo=UTC)
_NIGHT = datetime(2026, 8, 11, 3, 0, 0, tzinfo=UTC)


def _topo():
    return load_topology(_TOPO_PATH)


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------

def test_batch_is_deterministic():
    topo = _topo()
    a = panw_source.generate_batch(topo, _PEAK, _SEED)
    b = panw_source.generate_batch(topo, _PEAK, _SEED)
    assert a == b, "generate_batch must be deterministic for the same seed and tick"


# ---------------------------------------------------------------------------
# Volume
# ---------------------------------------------------------------------------

def test_peak_has_traffic_records():
    topo = _topo()
    msgs = panw_source.generate_batch(topo, _PEAK, _SEED)
    traffic = [m for m in msgs if "TRAFFIC" in m]
    assert len(traffic) >= 1, (
        f"Expected at least 1 TRAFFIC record at peak, got {len(traffic)}"
    )


def test_peak_busier_than_night():
    topo = _topo()
    peak = panw_source.generate_batch(topo, _PEAK, _SEED)
    night = panw_source.generate_batch(topo, _NIGHT, _SEED)
    assert len(peak) >= len(night), (
        f"Peak ({len(peak)} msgs) should be >= night ({len(night)} msgs)"
    )


# ---------------------------------------------------------------------------
# Source device
# ---------------------------------------------------------------------------

def test_all_records_from_fw_prod():
    topo = _topo()
    msgs = panw_source.generate_batch(topo, _PEAK, _SEED)
    for msg in msgs:
        assert "palo-fw-prod" in msg, (
            f"Expected palo-fw-prod in every record; got: {msg[:100]!r}"
        )


# ---------------------------------------------------------------------------
# Zone assignments
# ---------------------------------------------------------------------------

def test_traffic_egress_records_have_inside_outside_zones():
    topo = _topo()
    # Sample several ticks to ensure we get egress records
    all_msgs: list[str] = []
    for sec in range(10):
        t = datetime(2026, 8, 11, 12, 0, sec, tzinfo=UTC)
        all_msgs.extend(panw_source.generate_batch(topo, t, _SEED))
    egress = [m for m in all_msgs if "TRAFFIC" in m and "inside" in m and "outside" in m]
    assert len(egress) >= 1, (
        "Expected at least one TRAFFIC record with inside/outside zone assignment"
    )


def test_vpn_inbound_records_have_outside_inside_zones():
    """Parse TRAFFIC CSVs and assert both zone orientations are present.

    Egress records:     field[16]=="inside",  field[17]=="outside"
    VPN-inbound records: field[16]=="outside", field[17]=="inside"
    """
    topo = _topo()
    all_msgs: list[str] = []
    for sec in range(20):
        t = datetime(2026, 8, 11, 12, 0, sec, tzinfo=UTC)
        all_msgs.extend(panw_source.generate_batch(topo, t, _SEED))

    has_egress = False       # field[16]=="inside",  field[17]=="outside"
    has_vpn_inbound = False  # field[16]=="outside", field[17]=="inside"

    for msg in all_msgs:
        fields = _traffic_csv_fields(msg)
        if fields is None or len(fields) < 18:
            continue
        src_zone = fields[16]
        dst_zone = fields[17]
        if src_zone == "inside" and dst_zone == "outside":
            has_egress = True
        if src_zone == "outside" and dst_zone == "inside":
            has_vpn_inbound = True
        if has_egress and has_vpn_inbound:
            break

    assert has_egress, (
        "Expected at least one TRAFFIC record with src_zone=inside dst_zone=outside (egress)"
    )
    assert has_vpn_inbound, (
        "Expected at least one TRAFFIC record with src_zone=outside dst_zone=inside "
        "(VPN-inbound)"
    )


# ---------------------------------------------------------------------------
# THREAT rarity
# ---------------------------------------------------------------------------

def test_threat_records_are_rare_vs_traffic():
    """Over 120 ticks (~2 min), THREAT count should be << TRAFFIC count."""
    topo = _topo()
    all_msgs: list[str] = []
    for sec in range(120):
        t = datetime(2026, 8, 11, 12, sec // 60, sec % 60, tzinfo=UTC)
        all_msgs.extend(panw_source.generate_batch(topo, t, _SEED))
    threats = [m for m in all_msgs if "THREAT" in m]
    traffic = [m for m in all_msgs if "TRAFFIC" in m]
    assert len(traffic) > 0, "No TRAFFIC records emitted in 120 ticks"
    assert len(threats) < len(traffic), (
        f"Expected THREAT ({len(threats)}) < TRAFFIC ({len(traffic)})"
    )
