from datetime import UTC, datetime

from synthgen.common.patterns import in_backup_window, rate_multiplier

MON_PEAK = datetime(2026, 8, 10, 12, 0, tzinfo=UTC)   # Monday noon
MON_NIGHT = datetime(2026, 8, 10, 2, 30, tzinfo=UTC)  # Monday 02:30
SAT_PEAK = datetime(2026, 8, 8, 12, 0, tzinfo=UTC)    # Saturday noon

def test_deterministic():
    a = rate_multiplier(MON_PEAK, "user", "flow-x")
    b = rate_multiplier(MON_PEAK, "user", "flow-x")
    assert a == b

def test_different_keys_differ():
    assert rate_multiplier(MON_PEAK, "user", "flow-x") != rate_multiplier(MON_PEAK, "user", "flow-y")

def test_diurnal_peak_above_trough():
    assert rate_multiplier(MON_PEAK, "user", "k") > 2 * rate_multiplier(MON_NIGHT, "user", "k")

def test_weekend_dip_user_only():
    assert rate_multiplier(SAT_PEAK, "user", "k") < 0.5 * rate_multiplier(MON_PEAK, "user", "k")
    assert rate_multiplier(SAT_PEAK, "replication", "k") > 0.7 * rate_multiplier(MON_PEAK, "replication", "k")

def test_backup_window():
    assert in_backup_window(MON_NIGHT)
    assert not in_backup_window(MON_PEAK)

def test_multiplier_bounds():
    for hour in range(24):
        t = MON_PEAK.replace(hour=hour)
        m = rate_multiplier(t, "user", "k")
        assert 0.0 < m < 2.0

def test_jitter_stable_across_processes():
    # Pinned value: string-seeded PRNG must not vary with PYTHONHASHSEED.
    m = rate_multiplier(MON_PEAK, "user", "flow-x", seed=42)
    assert m == rate_multiplier(MON_PEAK, "user", "flow-x", seed=42)
    import subprocess
    import sys
    cmd = (
        "from datetime import datetime, UTC;"
        "from synthgen.common.patterns import rate_multiplier;"
        "print(repr(rate_multiplier(datetime(2026,8,10,12,0,tzinfo=UTC),'user','flow-x',seed=42)))"
    )
    out = subprocess.run(
        [sys.executable, "-c", cmd],
        capture_output=True, text=True, check=True).stdout.strip()
    assert out == repr(m)

def test_backup_window_naive_datetime_raises():
    from datetime import datetime as dt
    naive_dt = dt(2026, 8, 10, 2, 30)  # noqa: DTZ001
    try:
        in_backup_window(naive_dt)
        assert False, "Expected ValueError for naive datetime"
    except ValueError as e:
        assert "timezone-aware" in str(e)
