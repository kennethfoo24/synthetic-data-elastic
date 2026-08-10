"""Unit tests for meraki_source.generate_batch."""
from __future__ import annotations

from datetime import UTC, datetime

from synthgen.common.topology import load_topology
from synthgen.syslog_gen.meraki_source import generate_batch

TOPO = load_topology("topology/network.yaml")
PEAK = datetime(2026, 8, 11, 12, 0, 0, tzinfo=UTC)
NIGHT = datetime(2026, 8, 11, 3, 0, 0, tzinfo=UTC)


def test_batch_is_deterministic():
    assert generate_batch(TOPO, PEAK) == generate_batch(TOPO, PEAK)


def test_batch_different_seed_differs():
    assert generate_batch(TOPO, PEAK, seed=1) != generate_batch(TOPO, PEAK, seed=2)


def test_batch_returns_list_of_strings():
    batch = generate_batch(TOPO, PEAK)
    assert isinstance(batch, list)
    assert all(isinstance(line, str) for line in batch)


def test_batch_nonempty_at_peak():
    batch = generate_batch(TOPO, PEAK)
    assert len(batch) >= 1


def test_peak_busier_than_night():
    peak = sum(len(generate_batch(TOPO, PEAK.replace(second=s))) for s in range(60))
    night = sum(len(generate_batch(TOPO, NIGHT.replace(second=s))) for s in range(60))
    assert peak > night


def test_mx_emits_flows_and_urls():
    lines = [l for s in range(60) for l in generate_batch(TOPO, PEAK.replace(second=s))]
    mx_lines = [l for l in lines if "meraki-mx-01" in l]
    assert any(" flows " in l for l in mx_lines), "no flows lines from meraki-mx-01"
    assert any(" urls " in l for l in mx_lines), "no urls lines from meraki-mx-01"


def test_ap_emits_events():
    lines = [l for s in range(60) for l in generate_batch(TOPO, PEAK.replace(second=s))]
    ap_lines = [l for l in lines if "meraki-ap-01" in l or "meraki-ap-02" in l]
    assert len(ap_lines) >= 1
    assert all(" events " in l for l in ap_lines)


def test_events_include_association_and_disassociation():
    lines = [l for s in range(120) for l in generate_batch(TOPO, PEAK.replace(second=s % 60,
             minute=s // 60))]
    assert any("type=association" in l for l in lines)
    assert any("type=disassociation" in l for l in lines)


def test_all_lines_start_with_meraki_priority():
    batch = generate_batch(TOPO, PEAK)
    assert all(l.startswith("<134>1 ") for l in batch)


def test_client_macs_are_deterministic():
    """Same tick → same MAC addresses in association events."""
    b1 = generate_batch(TOPO, PEAK)
    b2 = generate_batch(TOPO, PEAK)
    macs1 = sorted(l.split("client_mac='")[1].split("'")[0] for l in b1 if "client_mac='" in l)
    macs2 = sorted(l.split("client_mac='")[1].split("'")[0] for l in b2 if "client_mac='" in l)
    assert macs1 == macs2
