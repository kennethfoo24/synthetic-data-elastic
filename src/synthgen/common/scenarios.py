from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import UTC, datetime
from math import floor


@dataclass(frozen=True)
class ScenarioSpec:
    """Immutable specification for a repeating scenario event."""

    id: str
    source: str
    duration_s: int
    every_s: int = 10800
    jitter_s: int = 2700


def _id_stagger(spec_id: str, every_s: int, jitter_s: int) -> int:
    """Return a deterministic per-scenario constant offset in [0, every_s - jitter_s).

    Uses a djb2-style hash of the spec id bytes so the result is independent of
    PYTHONHASHSEED and stable across processes.
    """
    h = 5381
    for c in spec_id.encode():
        h = ((h << 5) + h + c) & 0xFFFFFFFF
    window = max(1, every_s - jitter_s)
    return h % window


def _firing_start_epoch(spec: ScenarioSpec, bucket: int, seed: int) -> int:
    """Return the Unix epoch second at which the firing for *bucket* begins.

    The offset within the bucket is composed of:
    - A constant stagger derived from the scenario id (spreads same-source starts)
    - A per-bucket jitter seeded by (seed, id, bucket) for cross-process determinism

    Both components are in [0, every_s) and their sum stays below every_s, so the
    firing start always belongs to the named bucket.
    """
    stagger = _id_stagger(spec.id, spec.every_s, spec.jitter_s)
    rng = random.Random(f"{seed}|{spec.id}|{bucket}")
    jitter = rng.randrange(0, spec.jitter_s)
    return bucket * spec.every_s + stagger + jitter


SCENARIOS: dict[str, ScenarioSpec] = {
    # ── Palo Alto Networks ─────────────────────────────────────────────────
    "panw.port_scan": ScenarioSpec(
        id="panw.port_scan", source="panw", duration_s=600
    ),
    "panw.malware_detect": ScenarioSpec(
        id="panw.malware_detect", source="panw", duration_s=1800
    ),
    "panw.vpn_flap": ScenarioSpec(
        id="panw.vpn_flap", source="panw", duration_s=1200
    ),
    # ── Cisco ASA ──────────────────────────────────────────────────────────
    "asa.brute_force": ScenarioSpec(
        id="asa.brute_force", source="asa", duration_s=300
    ),
    "asa.conn_storm": ScenarioSpec(
        id="asa.conn_storm", source="asa", duration_s=450
    ),
    "asa.failover": ScenarioSpec(
        id="asa.failover", source="asa", duration_s=1500
    ),
    # ── Cisco IOS ──────────────────────────────────────────────────────────
    "ios.intf_flap": ScenarioSpec(
        id="ios.intf_flap", source="ios", duration_s=360
    ),
    "ios.stp_reconverge": ScenarioSpec(
        id="ios.stp_reconverge", source="ios", duration_s=300
    ),
    "ios.cpu_spike": ScenarioSpec(
        id="ios.cpu_spike", source="ios", duration_s=1200
    ),
    # ── Cisco Meraki ───────────────────────────────────────────────────────
    "meraki.ap_offline": ScenarioSpec(
        id="meraki.ap_offline", source="meraki", duration_s=900
    ),
    "meraki.rogue_ap": ScenarioSpec(
        id="meraki.rogue_ap", source="meraki", duration_s=720
    ),
    "meraki.wan_failover": ScenarioSpec(
        id="meraki.wan_failover", source="meraki", duration_s=1800
    ),
    # ── MongoDB ────────────────────────────────────────────────────────────
    "mongo.slow_query_storm": ScenarioSpec(
        id="mongo.slow_query_storm", source="mongodb", duration_s=1500
    ),
    "mongo.repl_lag": ScenarioSpec(
        id="mongo.repl_lag", source="mongodb", duration_s=1800
    ),
    "mongo.conn_exhaustion": ScenarioSpec(
        id="mongo.conn_exhaustion", source="mongodb", duration_s=1500
    ),
    # ── PostgreSQL ─────────────────────────────────────────────────────────
    "pg.deadlock": ScenarioSpec(
        id="pg.deadlock", source="postgresql", duration_s=300
    ),
    "pg.vacuum_load": ScenarioSpec(
        id="pg.vacuum_load", source="postgresql", duration_s=3600
    ),
    "pg.seqscan_regression": ScenarioSpec(
        id="pg.seqscan_regression", source="postgresql", duration_s=1200
    ),
    # ── HPE ────────────────────────────────────────────────────────────────
    "hpe.fan_failure": ScenarioSpec(
        id="hpe.fan_failure", source="hpe", duration_s=1800
    ),
    "hpe.port_saturation": ScenarioSpec(
        id="hpe.port_saturation", source="hpe", duration_s=1500
    ),
    "hpe.raid_degraded": ScenarioSpec(
        id="hpe.raid_degraded", source="hpe", duration_s=1800
    ),
    # ── Dell ───────────────────────────────────────────────────────────────
    "dell.psu_failure": ScenarioSpec(
        id="dell.psu_failure", source="dell", duration_s=1500
    ),
    "dell.mem_leak": ScenarioSpec(
        id="dell.mem_leak", source="dell", duration_s=3600
    ),
    "dell.capacity_breach": ScenarioSpec(
        id="dell.capacity_breach", source="dell", duration_s=3600
    ),
}


def active_window(
    spec: ScenarioSpec, t: datetime, seed: int
) -> tuple[datetime, datetime] | None:
    """Return the (start, end) of the firing that contains *t*, or None.

    Checks both the current and previous time buckets: a firing that starts near
    the end of bucket N can remain active well into bucket N+1 (maximum spillover
    is duration_s seconds, which is at most 3600 s for long scenarios).
    """
    if t.tzinfo is None:
        raise ValueError("t must be timezone-aware")
    epoch = t.timestamp()
    bucket = floor(epoch / spec.every_s)
    for b in (bucket, bucket - 1):
        start_ep = _firing_start_epoch(spec, b, seed)
        end_ep = start_ep + spec.duration_s
        if start_ep <= epoch < end_ep:
            return (
                datetime.fromtimestamp(start_ep, tz=UTC),
                datetime.fromtimestamp(end_ep, tz=UTC),
            )
    return None


def fires_at(spec: ScenarioSpec, t: datetime, seed: int) -> bool:
    """Return True when the scenario is actively firing at time *t*."""
    return active_window(spec, t, seed) is not None


def phase(spec: ScenarioSpec, t: datetime, seed: int) -> float | None:
    """Return progress through the active firing window in [0.0, 1.0), or None.

    0.0 == firing just started; values approaching 1.0 == near completion.
    Callers can use this to ramp anomaly magnitude smoothly over the window.
    """
    window = active_window(spec, t, seed)
    if window is None:
        return None
    start, _ = window
    return (t - start).total_seconds() / spec.duration_s


def active_scenarios(
    source: str, t: datetime, seed: int
) -> list[tuple[ScenarioSpec, float]]:
    """Return all scenarios for *source* currently firing, each with its phase.

    Raises ValueError for tz-naive *t*.
    """
    if t.tzinfo is None:
        raise ValueError("t must be timezone-aware")
    result: list[tuple[ScenarioSpec, float]] = []
    for spec in SCENARIOS.values():
        if spec.source != source:
            continue
        p = phase(spec, t, seed)
        if p is not None:
            result.append((spec, p))
    return result
