from __future__ import annotations

import subprocess
import sys
from datetime import UTC, datetime, timedelta
from itertools import combinations

from synthgen.common.scenarios import (
    SCENARIOS,
    ScenarioSpec,
    _firing_start_epoch,
    active_scenarios,
    active_window,
    fires_at,
    phase,
)

_SEED = 42
_START = datetime(2026, 1, 1, tzinfo=UTC)
_END = _START + timedelta(days=7)


# ── helpers ───────────────────────────────────────────────────────────────────


def _firings_in_range(
    spec: ScenarioSpec, start: datetime, end: datetime, seed: int
) -> list[int]:
    """Return sorted list of firing-start epochs that begin inside [start, end)."""
    start_ep = int(start.timestamp())
    end_ep = int(end.timestamp())
    b0 = start_ep // spec.every_s - 1
    b1 = end_ep // spec.every_s + 1
    return sorted(
        fe
        for b in range(b0, b1 + 1)
        if start_ep <= (fe := _firing_start_epoch(spec, b, seed)) < end_ep
    )


# ── tests ─────────────────────────────────────────────────────────────────────


def test_cross_process_determinism():
    """Firing schedule must be identical across processes (PYTHONHASHSEED-immune)."""
    spec = SCENARIOS["asa.brute_force"]
    bucket = 100
    expected = _firing_start_epoch(spec, bucket, _SEED)

    cmd = (
        "from synthgen.common.scenarios import _firing_start_epoch, SCENARIOS;"
        "spec = SCENARIOS['asa.brute_force'];"
        f"print(_firing_start_epoch(spec, 100, {_SEED}))"
    )
    out = subprocess.run(
        [sys.executable, "-c", cmd],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    assert out == str(expected), (
        f"cross-process mismatch: expected {expected}, got {out}"
    )


def test_scenario_count():
    """SCENARIOS must contain exactly 24 entries."""
    assert len(SCENARIOS) == 24


def test_fire_count_7days():
    """Each scenario must fire 50–62 times over a simulated 7-day window.

    With every_s=10800 there are 56 full buckets in 7 days; 50–62 accounts for
    boundary effects from the constant id stagger and per-bucket jitter.
    """
    for spec in SCENARIOS.values():
        firings = _firings_in_range(spec, _START, _END, _SEED)
        count = len(firings)
        assert 50 <= count <= 62, (
            f"{spec.id} fired {count} times over 7 days (expected 50–62)"
        )


def test_window_length_equals_duration():
    """Every firing window spans exactly duration_s seconds."""
    bucket = 500
    for spec in SCENARIOS.values():
        start_ep = _firing_start_epoch(spec, bucket, _SEED)
        # Sample at the midpoint so active_window reliably finds the window.
        mid_t = datetime.fromtimestamp(start_ep + spec.duration_s // 2, tz=UTC)
        win = active_window(spec, mid_t, _SEED)
        assert win is not None, f"{spec.id}: active_window returned None at midpoint"
        start_dt, end_dt = win
        length = (end_dt - start_dt).total_seconds()
        assert length == spec.duration_s, (
            f"{spec.id}: window length {length} != duration {spec.duration_s}"
        )


def test_phase_monotonic_and_bounded():
    """Phase must be in [0.0, 1.0) and strictly increase within a firing window."""
    bucket = 500
    for spec in SCENARIOS.values():
        start_ep = _firing_start_epoch(spec, bucket, _SEED)
        steps = max(10, spec.duration_s // 60)
        prev_p: float | None = None
        for i in range(steps):
            offset = int(i * spec.duration_s / steps)
            t = datetime.fromtimestamp(start_ep + offset, tz=UTC)
            p = phase(spec, t, _SEED)
            assert p is not None, f"{spec.id}: phase is None at offset {offset}s"
            assert 0.0 <= p < 1.0, f"{spec.id}: phase {p} not in [0, 1)"
            if prev_p is not None:
                assert p > prev_p, (
                    f"{spec.id}: phase not strictly monotonic at offset {offset}s "
                    f"({prev_p} -> {p})"
                )
            prev_p = p


def test_active_scenarios_source_filter():
    """active_scenarios must return only specs whose source matches the argument."""
    # Sample multiple timestamps to increase the chance of hitting active windows.
    test_times = [
        datetime(2026, 8, 10, h, 0, tzinfo=UTC) for h in range(0, 24, 3)
    ]
    sources = {spec.source for spec in SCENARIOS.values()}
    for source in sources:
        for t in test_times:
            results = active_scenarios(source, t, _SEED)
            for spec, p in results:
                assert spec.source == source, (
                    f"active_scenarios('{source}') returned spec with source "
                    f"'{spec.source}' ({spec.id})"
                )


def test_same_source_collision_rate_below_5pct():
    """Same-source scenario pairs must start in the same UTC minute < 5 % of the time.

    The constant id stagger and per-bucket jitter (seeded per spec id) together
    spread firing times so that pairwise minute collisions stay rare.
    """
    start_ep = int(_START.timestamp())
    end_ep = int(_END.timestamp())

    sources: dict[str, list[ScenarioSpec]] = {}
    for spec in SCENARIOS.values():
        sources.setdefault(spec.source, []).append(spec)

    for source, specs in sources.items():
        for spec_a, spec_b in combinations(specs, 2):
            b0 = start_ep // spec_a.every_s
            b1 = end_ep // spec_a.every_s + 1
            total = 0
            collisions = 0
            for b in range(b0, b1 + 1):
                fe_a = _firing_start_epoch(spec_a, b, _SEED)
                fe_b = _firing_start_epoch(spec_b, b, _SEED)
                in_a = start_ep <= fe_a < end_ep
                in_b = start_ep <= fe_b < end_ep
                if in_a and in_b:
                    total += 1
                    if fe_a // 60 == fe_b // 60:
                        collisions += 1
            rate = collisions / total if total > 0 else 0.0
            assert rate < 0.05, (
                f"{source}: {spec_a.id} vs {spec_b.id} "
                f"minute-collision rate {rate:.1%} >= 5% "
                f"({collisions}/{total} buckets)"
            )


def test_naive_datetime_raises():
    """tz-naive datetimes must raise ValueError containing 'timezone-aware'."""
    from datetime import datetime as dt

    naive = dt(2026, 8, 10, 12, 0)  # noqa: DTZ001
    spec = SCENARIOS["panw.port_scan"]

    try:
        active_window(spec, naive, _SEED)
        assert False, "Expected ValueError from active_window"
    except ValueError as exc:
        assert "timezone-aware" in str(exc), f"Unexpected message: {exc}"

    try:
        active_scenarios("panw", naive, _SEED)
        assert False, "Expected ValueError from active_scenarios"
    except ValueError as exc:
        assert "timezone-aware" in str(exc), f"Unexpected message: {exc}"


def test_fires_at_consistent_with_active_window():
    """fires_at must agree with active_window on whether t is inside a window."""
    bucket = 200
    for spec in SCENARIOS.values():
        start_ep = _firing_start_epoch(spec, bucket, _SEED)
        mid_t = datetime.fromtimestamp(start_ep + spec.duration_s // 2, tz=UTC)
        assert fires_at(spec, mid_t, _SEED) is True
        # Just before the window (if bucket > 0)
        before_t = datetime.fromtimestamp(start_ep - 1, tz=UTC)
        assert fires_at(spec, before_t, _SEED) is (active_window(spec, before_t, _SEED) is not None)
