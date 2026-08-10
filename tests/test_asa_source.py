from datetime import UTC, datetime

from synthgen.common.topology import load_topology
from synthgen.syslog_gen.asa_source import generate_batch

TOPO = load_topology("topology/network.yaml")
PEAK = datetime(2026, 8, 10, 12, 0, 0, tzinfo=UTC)
NIGHT = datetime(2026, 8, 10, 2, 30, 0, tzinfo=UTC)

def test_batch_is_deterministic():
    assert generate_batch(TOPO, PEAK) == generate_batch(TOPO, PEAK)

def test_batch_contains_valid_asa_lines():
    batch = generate_batch(TOPO, PEAK)
    assert len(batch) >= 1
    assert all("%ASA-" in line and "cisco-asa-dr" in line for line in batch)

def test_peak_busier_than_night():
    # Average over 60 ticks to smooth jitter.
    peak = sum(len(generate_batch(TOPO, PEAK.replace(second=s))) for s in range(60))
    night = sum(len(generate_batch(TOPO, NIGHT.replace(second=s))) for s in range(60))
    assert peak > night

def test_mix_includes_denies():
    lines = [l for s in range(60) for l in generate_batch(TOPO, PEAK.replace(second=s))]
    assert any("106023" in l for l in lines)
    assert any("302013" in l for l in lines)
