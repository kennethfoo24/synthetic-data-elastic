"""
Pure functions for SNMP scenario OID value computation.

``scenario_value(oid_kind, vendor, t, seed)`` returns the integer value that
the named OID should report during an active scenario window, or ``None`` when
no scenario is firing (caller falls back to the baseline rendered by
:func:`render_snmprec`).

Design contract
---------------
All functions are **deterministic** from ``(t, seed)``: identical inputs always
produce identical output, independent of process state or wall clock.  This lets
the live scenario rewriter and an offline SNMP history backfill reproduce exactly
the same value curves.

The ``phase`` of a scenario is in ``[0.0, 1.0)`` — 0.0 at the start of the
firing window, approaching 1.0 near the end.  Value curves are expressed as
functions of ``phase`` so callers need only pass ``(oid_kind, vendor, t, seed)``.
"""
from __future__ import annotations

import math
from datetime import datetime

from synthgen.common.scenarios import SCENARIOS
from synthgen.common.scenarios import phase as _phase

# ---------------------------------------------------------------------------
# OID registry — maps oid_kind to the OID string used in .snmprec files.
# These OIDs are emitted by render.py (baseline) and overridden by the rewriter.
# ---------------------------------------------------------------------------

#: OID strings for HPE scenario gauges (all HPE devices).
HPE_SCENARIO_OIDS: dict[str, str] = {
    "fan_status":    "1.3.6.1.4.1.11.2.36.1.1.2.1.0",   # 2=OK, 4=failed
    "temperature_c": "1.3.6.1.4.1.11.2.36.1.1.3.1.5",   # Celsius
    "port_util_pct": "1.3.6.1.4.1.11.2.36.1.1.5.1.0",   # 0–100 %
    "raid_status":   "1.3.6.1.4.1.11.2.36.1.1.12.1.0",  # 2=OK, 3=degraded
}

#: OID strings for Dell scenario gauges (all Dell devices).
#: ``capacity_pct`` (99999 OID) is only emitted for storage-role devices.
DELL_SCENARIO_OIDS: dict[str, str] = {
    "psu_status":   "1.3.6.1.4.1.674.10892.5.4.600.12.1.5.1.1",   # 3=OK, 11=failed
    "psu_power_w":  "1.3.6.1.4.1.674.10892.5.4.600.30.1.6.1.1",   # watts
    "mem_used_pct": "1.3.6.1.4.1.674.10892.5.4.1100.50.1.6.1.1",  # 0–100 %
    "capacity_pct": "1.3.6.1.4.1.99999.1.1.0",                     # 0–100 % (storage only)
}

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def scenario_value(oid_kind: str, vendor: str, t: datetime, seed: int) -> int | None:
    """Return the scenario-adjusted integer value for *oid_kind*, or ``None``.

    ``None`` means no scenario is active for this OID kind — callers should use
    the baseline numeric-variation value rendered by :func:`render_snmprec`.

    Parameters
    ----------
    oid_kind:
        One of the keys in :data:`HPE_SCENARIO_OIDS` or :data:`DELL_SCENARIO_OIDS`.
    vendor:
        ``"hpe"`` or ``"dell"`` — matched against the scenario source.
    t:
        Timezone-aware :class:`datetime` for the query instant.
    seed:
        Integer seed passed through to the scenario schedule.
    """
    if vendor == "hpe":
        return _hpe_value(oid_kind, t, seed)
    if vendor == "dell":
        return _dell_value(oid_kind, t, seed)
    return None


# ---------------------------------------------------------------------------
# HPE scenario value functions
# ---------------------------------------------------------------------------


def _hpe_value(oid_kind: str, t: datetime, seed: int) -> int | None:
    if oid_kind == "fan_status":
        return _hpe_fan_status(t, seed)
    if oid_kind == "temperature_c":
        return _hpe_temperature(t, seed)
    if oid_kind == "port_util_pct":
        return _hpe_port_util(t, seed)
    if oid_kind == "raid_status":
        return _hpe_raid_status(t, seed)
    return None


def _hpe_fan_status(t: datetime, seed: int) -> int | None:
    """2 = OK (baseline), 4 = failed (hpe.fan_failure active at phase >= 0.1)."""
    p = _phase(SCENARIOS["hpe.fan_failure"], t, seed)
    if p is None:
        return None
    return 4 if p >= 0.1 else 2


def _hpe_temperature(t: datetime, seed: int) -> int | None:
    """Temperature climbs from 25 °C to 75 °C linearly over the fan-failure window."""
    p = _phase(SCENARIOS["hpe.fan_failure"], t, seed)
    if p is None:
        return None
    return int(25 + 50 * p)


def _hpe_port_util(t: datetime, seed: int) -> int | None:
    """Port utilisation near 100 % during hpe.port_saturation (sinusoidal 85–99 %)."""
    p = _phase(SCENARIOS["hpe.port_saturation"], t, seed)
    if p is None:
        return None
    # Oscillate between 85 and 99 % with a full sinusoidal period over the window.
    return min(99, int(92 + 7 * math.sin(p * 2 * math.pi)))


def _hpe_raid_status(t: datetime, seed: int) -> int | None:
    """2 = OK (baseline), 3 = degraded (hpe.raid_degraded firing)."""
    p = _phase(SCENARIOS["hpe.raid_degraded"], t, seed)
    if p is None:
        return None
    return 3  # degraded for the entire window


# ---------------------------------------------------------------------------
# Dell scenario value functions
# ---------------------------------------------------------------------------


def _dell_value(oid_kind: str, t: datetime, seed: int) -> int | None:
    if oid_kind == "psu_status":
        return _dell_psu_status(t, seed)
    if oid_kind == "psu_power_w":
        return _dell_psu_power(t, seed)
    if oid_kind == "mem_used_pct":
        return _dell_mem_pct(t, seed)
    if oid_kind == "capacity_pct":
        return _dell_capacity_pct(t, seed)
    return None


def _dell_psu_status(t: datetime, seed: int) -> int | None:
    """3 = presentAndOK (baseline), 11 = failed (dell.psu_failure at phase >= 0.15)."""
    p = _phase(SCENARIOS["dell.psu_failure"], t, seed)
    if p is None:
        return None
    return 11 if p >= 0.15 else 3


def _dell_psu_power(t: datetime, seed: int) -> int | None:
    """Power draw (watts) during dell.psu_failure: normal then collapses as PSU fails."""
    p = _phase(SCENARIOS["dell.psu_failure"], t, seed)
    if p is None:
        return None
    if p < 0.15:
        return 350  # normal draw before failure event
    # After failure the draw collapses toward zero with slight noise.
    collapse = (p - 0.15) / 0.85  # 0.0 → 1.0 over post-failure period
    return max(0, int(350 * (1.0 - collapse) + 12 * math.sin(p * 25)))


def _dell_mem_pct(t: datetime, seed: int) -> int | None:
    """Memory used % during dell.mem_leak: sawtooth — climbs 50 → 92 %, resets."""
    p = _phase(SCENARIOS["dell.mem_leak"], t, seed)
    if p is None:
        return None
    # Linearly climbs from 50 % at phase=0 to 92 % at phase→1, then resets on
    # next window start (the natural bucket boundary creates the sawtooth edge).
    return int(50 + 42 * p)


def _dell_capacity_pct(t: datetime, seed: int) -> int | None:
    """Storage capacity % during dell.capacity_breach.

    Phase 0.00–0.33 : rises from 82 % to 87 %  (crosses 85 % threshold)
    Phase 0.33–0.67 : rises from 87 % to 93 %  (crosses 90 % threshold)
    Phase 0.67–1.00 : drops from 93 % to 75 %  (cleanup / reclaim)
    """
    p = _phase(SCENARIOS["dell.capacity_breach"], t, seed)
    if p is None:
        return None
    if p < 0.33:
        return int(82 + (87 - 82) * (p / 0.33))
    if p < 0.67:
        return int(87 + (93 - 87) * ((p - 0.33) / 0.34))
    return int(93 - (93 - 75) * ((p - 0.67) / 0.33))
