"""Tests for the NetFlow v9 flow-record source (pure generator)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from synthgen.common.topology import load_topology
from synthgen.netflow_gen.encoder import FlowRecord
from synthgen.netflow_gen.source import generate_records

TOPO_PATH = "topology/network.yaml"

# Monday noon UTC — peak traffic, outside backup window
T_PEAK = datetime(2026, 8, 10, 12, 0, 0, tzinfo=UTC)
# Monday 02:00 UTC — inside backup window (1-3 UTC)
T_BACKUP = datetime(2026, 8, 10, 2, 0, 0, tzinfo=UTC)


def topo():
    return load_topology(TOPO_PATH)


# ---------------------------------------------------------------------------
# Basic shape
# ---------------------------------------------------------------------------

def test_returns_list_of_flow_records():
    records = generate_records(topo(), T_PEAK)
    assert isinstance(records, list)
    assert all(isinstance(r, FlowRecord) for r in records)


def test_two_records_per_topology_flow():
    t = topo()
    records = generate_records(t, T_PEAK)
    assert len(records) == 2 * len(t.flows)


def test_protocol_is_tcp_or_udp():
    records = generate_records(topo(), T_PEAK)
    for r in records:
        assert r.protocol in (6, 17), f"unexpected protocol {r.protocol}"


# ---------------------------------------------------------------------------
# Forward / reverse pair semantics
# ---------------------------------------------------------------------------

def test_forward_reverse_addresses_are_swapped():
    """Records are emitted in (forward, reverse) pairs."""
    records = generate_records(topo(), T_PEAK)
    for i in range(0, len(records), 2):
        fwd = records[i]
        rev = records[i + 1]
        assert fwd.src_addr == rev.dst_addr, "forward src should equal reverse dst"
        assert fwd.dst_addr == rev.src_addr, "forward dst should equal reverse src"
        assert fwd.dst_port == rev.src_port, "forward dst_port should equal reverse src_port"


def test_reverse_bytes_approximately_ten_percent_of_forward():
    records = generate_records(topo(), T_PEAK)
    for i in range(0, len(records), 2):
        fwd = records[i]
        rev = records[i + 1]
        # Reverse bytes = fwd_bytes // 10, min 1
        expected_rev = max(1, fwd.in_bytes // 10)
        assert rev.in_bytes == expected_rev


def test_reverse_pkts_lte_forward_pkts():
    records = generate_records(topo(), T_PEAK)
    for i in range(0, len(records), 2):
        assert records[i + 1].in_pkts <= records[i].in_pkts


# ---------------------------------------------------------------------------
# Backup-window overlay
# ---------------------------------------------------------------------------

def test_backup_flows_larger_inside_window():
    t = topo()
    records_peak = generate_records(t, T_PEAK)
    records_backup = generate_records(t, T_BACKUP)

    backup_flows = [f for f in t.flows if f.flow_class == "backup"]
    assert backup_flows, "topology must contain at least one backup flow"

    def total_fwd_bytes(records, flows):
        flow_dst_ports = {f.dst_port for f in flows}
        return sum(r.in_bytes for r in records[::2] if r.dst_port in flow_dst_ports)

    peak_bytes = total_fwd_bytes(records_peak, backup_flows)
    bk_bytes = total_fwd_bytes(records_backup, backup_flows)
    # Inside window: ×20; outside: ×0.05 → ratio should be >> 1
    assert bk_bytes > peak_bytes * 10


# ---------------------------------------------------------------------------
# Determinism and PRNG purity
# ---------------------------------------------------------------------------

def test_deterministic_same_seed():
    t = topo()
    r1 = generate_records(t, T_PEAK, seed=42)
    r2 = generate_records(t, T_PEAK, seed=42)
    assert r1 == r2


def test_different_seeds_produce_different_bytes():
    t = topo()
    r1 = generate_records(t, T_PEAK, seed=42)
    r2 = generate_records(t, T_PEAK, seed=99)
    # Rate multiplier jitter differs → at least some in_bytes differ
    assert any(a.in_bytes != b.in_bytes for a, b in zip(r1, r2))


def test_src_port_stable_within_minute_bucket():
    """Src port must not change within the same minute bucket."""
    t = topo()
    t0 = T_PEAK.replace(second=0)
    t30 = T_PEAK.replace(second=30)
    r0 = generate_records(t, t0, seed=42)
    r30 = generate_records(t, t30, seed=42)
    for a, b in zip(r0, r30):
        assert a.src_port == b.src_port, "src_port changed within same minute bucket"


def test_src_port_in_valid_range():
    records = generate_records(topo(), T_PEAK)
    for r in records[::2]:  # forward records only (reverse src_port = dst_port of flow)
        assert 1024 <= r.src_port <= 65000


# ---------------------------------------------------------------------------
# FIRST_SWITCHED / LAST_SWITCHED
# ---------------------------------------------------------------------------

def test_first_switched_before_last_switched():
    records = generate_records(topo(), T_PEAK)
    for r in records:
        assert r.first_switched < r.last_switched


def test_switched_times_within_tick():
    """Both timestamps should be within ~1 second of the current uptime."""
    records = generate_records(topo(), T_PEAK)
    sys_uptime_ms = int(T_PEAK.timestamp() * 1000) & 0xFFFFFFFF
    for r in records:
        assert r.last_switched < sys_uptime_ms
        assert r.first_switched < r.last_switched
        assert sys_uptime_ms - r.first_switched <= 1000


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------

def test_naive_datetime_raises():
    from datetime import datetime as dt
    with pytest.raises(ValueError, match="timezone-aware"):
        generate_records(topo(), dt(2026, 8, 10, 12, 0, 0))  # noqa: DTZ001
