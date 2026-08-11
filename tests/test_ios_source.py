from datetime import UTC, datetime

from synthgen.common.topology import load_topology
from synthgen.syslog_gen.ios_source import generate_batch

TOPO = load_topology("topology/network.yaml")
PEAK = datetime(2026, 8, 11, 12, 0, 0, tzinfo=UTC)
NIGHT = datetime(2026, 8, 11, 2, 30, 0, tzinfo=UTC)

IOS_NAMES = ["cisco-rtr-core-01", "cisco-rtr-core-02", "cisco-sw-access-01",
             "cisco-sw-access-02", "cisco-sw-access-03", "cisco-rtr-dr", "cisco-sw-dr-01"]


def test_batch_is_deterministic():
    assert generate_batch(TOPO, PEAK) == generate_batch(TOPO, PEAK)


def test_batch_contains_valid_ios_lines():
    batch = generate_batch(TOPO, PEAK)
    assert len(batch) >= 1
    # Every line must have a % mnemonic and come from a known IOS device
    for line in batch:
        assert "%" in line
        assert any(name in line for name in IOS_NAMES), f"Unknown device in: {line}"


def test_peak_busier_than_night():
    # Average over 60 ticks to smooth jitter.
    peak = sum(len(generate_batch(TOPO, PEAK.replace(second=s))) for s in range(60))
    night = sum(len(generate_batch(TOPO, NIGHT.replace(second=s))) for s in range(60))
    assert peak > night


def test_mix_includes_login_and_config():
    lines = [line for s in range(60) for line in generate_batch(TOPO, PEAK.replace(second=s))]
    assert any("LOGIN_SUCCESS" in line for line in lines)
    assert any("CONFIG_I" in line for line in lines)
    assert any("LOGGINGHOST_STARTSTOP" in line for line in lines)


def test_all_ios_devices_emit():
    lines = [line for s in range(5) for line in generate_batch(TOPO, PEAK.replace(second=s))]
    found = [name for name in IOS_NAMES if any(name in line for line in lines)]
    assert len(found) == len(IOS_NAMES), f"Only {len(found)} of {len(IOS_NAMES)} IOS devices emitting"


def test_link_updown_rare():
    lines = [line for s in range(60) for line in generate_batch(TOPO, PEAK.replace(second=s))]
    flap_lines = [line for line in lines if "UPDOWN" in line]
    ratio = len(flap_lines) / max(len(lines), 1)
    assert ratio < 0.05, f"Link flap ratio {ratio:.2%} exceeds 5%"


def test_seq_is_deterministic_across_calls():
    """Same (t, device) always yields the same seq numbers."""
    batch1 = generate_batch(TOPO, PEAK)
    batch2 = generate_batch(TOPO, PEAK)
    seqs1 = [line.split(">")[1].split(":")[0] for line in batch1]
    seqs2 = [line.split(">")[1].split(":")[0] for line in batch2]
    assert seqs1 == seqs2
