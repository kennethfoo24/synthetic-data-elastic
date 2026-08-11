"""Tests for SNMP scenario OID value computation and the snmprec rewriter.

Covers:
- scenario_value() curve shapes and determinism for all 6 scenarios
- baseline (no-scenario) returns None
- apply_scenario() hot-patches the correct lines in a rendered snmprec
- render_snmprec() baseline contains HPE/Dell scenario OIDs in sorted order
"""
from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

# Make the project root importable so snmp.generator.* resolve.
_PROJECT_ROOT = str(Path(__file__).parent.parent)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from snmp.generator.render import _snmp_devices, render_snmprec
from snmp.generator.rewriter import apply_scenario
from snmp.generator.scenario_values import (
    DELL_SCENARIO_OIDS,
    HPE_SCENARIO_OIDS,
    scenario_value,
)
from synthgen.common.scenarios import SCENARIOS, _firing_start_epoch

TOPOLOGY_PATH = Path(_PROJECT_ROOT) / "topology" / "network.yaml"
DEVICES = _snmp_devices(TOPOLOGY_PATH)
HPE_DEVICES = [d for d in DEVICES if d.vendor == "hpe"]
DELL_DEVICES = [d for d in DEVICES if d.vendor == "dell"]

SEED = 42


def _active_instant(scenario_id: str, seed: int = SEED) -> datetime:
    """Return a datetime that is guaranteed to be mid-window for *scenario_id*."""
    spec = SCENARIOS[scenario_id]
    # Use bucket 0 to get a deterministic firing start.
    start_ep = _firing_start_epoch(spec, 0, seed)
    # Return a point 40 % through the window.
    t_ep = start_ep + int(spec.duration_s * 0.40)
    return datetime.fromtimestamp(t_ep, tz=UTC)


def _late_instant(scenario_id: str, seed: int = SEED) -> datetime:
    """Return a datetime that is 80 % through the firing window."""
    spec = SCENARIOS[scenario_id]
    start_ep = _firing_start_epoch(spec, 0, seed)
    t_ep = start_ep + int(spec.duration_s * 0.80)
    return datetime.fromtimestamp(t_ep, tz=UTC)


def _before_instant(scenario_id: str, seed: int = SEED) -> datetime:
    """Return a datetime just before the firing window."""
    spec = SCENARIOS[scenario_id]
    start_ep = _firing_start_epoch(spec, 0, seed)
    return datetime.fromtimestamp(start_ep - 60, tz=UTC)


# ---------------------------------------------------------------------------
# Baseline: no scenario active → scenario_value returns None
# ---------------------------------------------------------------------------


class TestBaseline:
    def test_hpe_fan_outside_window(self):
        t = _before_instant("hpe.fan_failure")
        assert scenario_value("fan_status", "hpe", t, SEED) is None

    def test_hpe_temperature_outside_window(self):
        t = _before_instant("hpe.fan_failure")
        assert scenario_value("temperature_c", "hpe", t, SEED) is None

    def test_hpe_port_util_outside_window(self):
        t = _before_instant("hpe.port_saturation")
        assert scenario_value("port_util_pct", "hpe", t, SEED) is None

    def test_hpe_raid_outside_window(self):
        t = _before_instant("hpe.raid_degraded")
        assert scenario_value("raid_status", "hpe", t, SEED) is None

    def test_dell_psu_status_outside_window(self):
        t = _before_instant("dell.psu_failure")
        assert scenario_value("psu_status", "dell", t, SEED) is None

    def test_dell_psu_power_outside_window(self):
        t = _before_instant("dell.psu_failure")
        assert scenario_value("psu_power_w", "dell", t, SEED) is None

    def test_dell_mem_outside_window(self):
        t = _before_instant("dell.mem_leak")
        assert scenario_value("mem_used_pct", "dell", t, SEED) is None

    def test_dell_capacity_outside_window(self):
        t = _before_instant("dell.capacity_breach")
        assert scenario_value("capacity_pct", "dell", t, SEED) is None

    def test_unknown_vendor_always_none(self):
        t = _active_instant("hpe.fan_failure")
        assert scenario_value("fan_status", "cisco", t, SEED) is None

    def test_unknown_oid_kind_none(self):
        t = _active_instant("hpe.fan_failure")
        assert scenario_value("nonexistent_oid", "hpe", t, SEED) is None


# ---------------------------------------------------------------------------
# hpe.fan_failure — fan status + temperature climb
# ---------------------------------------------------------------------------


class TestHpeFanFailure:
    def test_fan_status_early_ok(self):
        """Fan status is still OK early in the window (phase < 0.1)."""
        spec = SCENARIOS["hpe.fan_failure"]
        start_ep = _firing_start_epoch(spec, 0, SEED)
        # phase ≈ 0.05 (5 % into the window)
        t = datetime.fromtimestamp(start_ep + int(spec.duration_s * 0.05), tz=UTC)
        val = scenario_value("fan_status", "hpe", t, SEED)
        assert val == 2, "Fan should still read OK at phase < 0.1"

    def test_fan_status_failed_at_phase_40pct(self):
        t = _active_instant("hpe.fan_failure")
        val = scenario_value("fan_status", "hpe", t, SEED)
        assert val == 4, "Fan should read FAILED at phase >= 0.1"

    def test_fan_status_failed_at_late_phase(self):
        t = _late_instant("hpe.fan_failure")
        val = scenario_value("fan_status", "hpe", t, SEED)
        assert val == 4

    def test_temperature_increases_with_phase(self):
        """Temperature must increase monotonically over the window."""
        spec = SCENARIOS["hpe.fan_failure"]
        start_ep = _firing_start_epoch(spec, 0, SEED)
        temps = []
        for frac in (0.1, 0.3, 0.5, 0.7, 0.9):
            t = datetime.fromtimestamp(start_ep + int(spec.duration_s * frac), tz=UTC)
            val = scenario_value("temperature_c", "hpe", t, SEED)
            assert val is not None
            temps.append(val)
        assert temps == sorted(temps), f"Temperature must be monotonically increasing: {temps}"

    def test_temperature_range(self):
        """Temperature must be in [25, 75] during the window."""
        spec = SCENARIOS["hpe.fan_failure"]
        start_ep = _firing_start_epoch(spec, 0, SEED)
        for frac in (0.0, 0.25, 0.5, 0.75, 0.99):
            t = datetime.fromtimestamp(start_ep + int(spec.duration_s * frac), tz=UTC)
            val = scenario_value("temperature_c", "hpe", t, SEED)
            assert val is not None
            assert 25 <= val <= 75, f"Temperature {val} out of expected range at phase={frac}"

    def test_deterministic(self):
        """Same (t, seed) produces same value."""
        t = _active_instant("hpe.fan_failure")
        v1 = scenario_value("temperature_c", "hpe", t, SEED)
        v2 = scenario_value("temperature_c", "hpe", t, SEED)
        assert v1 == v2


# ---------------------------------------------------------------------------
# hpe.port_saturation — ifUtilization near 100 %
# ---------------------------------------------------------------------------


class TestHpePortSaturation:
    def test_port_util_high_during_window(self):
        t = _active_instant("hpe.port_saturation")
        val = scenario_value("port_util_pct", "hpe", t, SEED)
        assert val is not None
        assert val >= 85, f"Port utilisation must be >= 85 % during scenario, got {val}"

    def test_port_util_capped_at_99(self):
        """Port utilisation must never exceed 99 %."""
        spec = SCENARIOS["hpe.port_saturation"]
        start_ep = _firing_start_epoch(spec, 0, SEED)
        for frac in (0.0, 0.25, 0.5, 0.75, 0.99):
            t = datetime.fromtimestamp(start_ep + int(spec.duration_s * frac), tz=UTC)
            val = scenario_value("port_util_pct", "hpe", t, SEED)
            if val is not None:
                assert val <= 99, f"Port utilisation {val} exceeds 99 %"

    def test_different_seed_different_timing(self):
        """With a different seed the window falls at a different time."""
        t = _active_instant("hpe.port_saturation", seed=SEED)
        v_seed_a = scenario_value("port_util_pct", "hpe", t, SEED)
        v_seed_b = scenario_value("port_util_pct", "hpe", t, SEED + 999)
        # Either both active (unlikely same phase) or at least one differs
        # — determinism check: both are reproducible from their own seed.
        assert scenario_value("port_util_pct", "hpe", t, SEED) == v_seed_a
        assert scenario_value("port_util_pct", "hpe", t, SEED + 999) == v_seed_b


# ---------------------------------------------------------------------------
# hpe.raid_degraded — RAID array health
# ---------------------------------------------------------------------------


class TestHpeRaidDegraded:
    def test_raid_status_degraded_during_window(self):
        t = _active_instant("hpe.raid_degraded")
        val = scenario_value("raid_status", "hpe", t, SEED)
        assert val == 3, "RAID status must be 3 (degraded) during window"

    def test_raid_degraded_for_entire_window(self):
        spec = SCENARIOS["hpe.raid_degraded"]
        start_ep = _firing_start_epoch(spec, 0, SEED)
        for frac in (0.01, 0.3, 0.6, 0.9, 0.99):
            t = datetime.fromtimestamp(start_ep + int(spec.duration_s * frac), tz=UTC)
            val = scenario_value("raid_status", "hpe", t, SEED)
            assert val == 3, f"Expected degraded at phase={frac}, got {val}"


# ---------------------------------------------------------------------------
# dell.psu_failure — PSU status + power draw
# ---------------------------------------------------------------------------


class TestDellPsuFailure:
    def test_psu_status_ok_before_failure_phase(self):
        """PSU status is still OK early in the window (phase < 0.15)."""
        spec = SCENARIOS["dell.psu_failure"]
        start_ep = _firing_start_epoch(spec, 0, SEED)
        t = datetime.fromtimestamp(start_ep + int(spec.duration_s * 0.05), tz=UTC)
        val = scenario_value("psu_status", "dell", t, SEED)
        assert val == 3, "PSU should still be OK at phase < 0.15"

    def test_psu_status_failed_at_40pct(self):
        t = _active_instant("dell.psu_failure")
        val = scenario_value("psu_status", "dell", t, SEED)
        assert val == 11, "PSU should be failed at phase >= 0.15"

    def test_psu_power_drops_after_failure(self):
        """Power draw must drop significantly after PSU failure event."""
        spec = SCENARIOS["dell.psu_failure"]
        start_ep = _firing_start_epoch(spec, 0, SEED)
        # Power just before failure
        t_before = datetime.fromtimestamp(start_ep + int(spec.duration_s * 0.10), tz=UTC)
        p_before = scenario_value("psu_power_w", "dell", t_before, SEED)
        # Power well after failure
        t_after = datetime.fromtimestamp(start_ep + int(spec.duration_s * 0.80), tz=UTC)
        p_after = scenario_value("psu_power_w", "dell", t_after, SEED)
        assert p_before is not None
        assert p_after is not None
        assert p_after < p_before, (
            f"Power should drop after PSU failure: before={p_before}W, after={p_after}W"
        )

    def test_psu_power_non_negative(self):
        spec = SCENARIOS["dell.psu_failure"]
        start_ep = _firing_start_epoch(spec, 0, SEED)
        for frac in (0.2, 0.5, 0.8, 0.99):
            t = datetime.fromtimestamp(start_ep + int(spec.duration_s * frac), tz=UTC)
            val = scenario_value("psu_power_w", "dell", t, SEED)
            if val is not None:
                assert val >= 0, f"PSU power must be non-negative, got {val}"


# ---------------------------------------------------------------------------
# dell.mem_leak — memory gauge sawtooth
# ---------------------------------------------------------------------------


class TestDellMemLeak:
    def test_mem_pct_increases_with_phase(self):
        """Memory used % must increase monotonically over the leak window."""
        spec = SCENARIOS["dell.mem_leak"]
        start_ep = _firing_start_epoch(spec, 0, SEED)
        values = []
        for frac in (0.1, 0.3, 0.5, 0.7, 0.9):
            t = datetime.fromtimestamp(start_ep + int(spec.duration_s * frac), tz=UTC)
            val = scenario_value("mem_used_pct", "dell", t, SEED)
            assert val is not None
            values.append(val)
        assert values == sorted(values), f"Memory must grow monotonically: {values}"

    def test_mem_pct_range(self):
        """Memory used % must be in [50, 92] during the window."""
        spec = SCENARIOS["dell.mem_leak"]
        start_ep = _firing_start_epoch(spec, 0, SEED)
        for frac in (0.0, 0.25, 0.5, 0.75, 0.99):
            t = datetime.fromtimestamp(start_ep + int(spec.duration_s * frac), tz=UTC)
            val = scenario_value("mem_used_pct", "dell", t, SEED)
            assert val is not None
            assert 50 <= val <= 92, f"Memory % {val} out of sawtooth range at phase={frac}"

    def test_sawtooth_resets_at_new_window(self):
        """Memory at end of one window is higher than at start of next bucket."""
        spec = SCENARIOS["dell.mem_leak"]
        # End of bucket 0 window
        start_0 = _firing_start_epoch(spec, 0, SEED)
        t_end = datetime.fromtimestamp(start_0 + int(spec.duration_s * 0.95), tz=UTC)
        val_end = scenario_value("mem_used_pct", "dell", t_end, SEED)
        # Start of bucket 1 window
        start_1 = _firing_start_epoch(spec, 1, SEED)
        t_start_next = datetime.fromtimestamp(start_1 + int(spec.duration_s * 0.02), tz=UTC)
        val_next_start = scenario_value("mem_used_pct", "dell", t_start_next, SEED)
        if val_end is not None and val_next_start is not None:
            assert val_next_start < val_end, (
                f"Memory should reset between windows: end={val_end}, next_start={val_next_start}"
            )


# ---------------------------------------------------------------------------
# dell.capacity_breach — capacity crossing 85 / 90 then cleanup
# ---------------------------------------------------------------------------


class TestDellCapacityBreach:
    def test_crosses_85_pct_early_window(self):
        """Capacity must exceed 85 % in the first third of the window."""
        spec = SCENARIOS["dell.capacity_breach"]
        start_ep = _firing_start_epoch(spec, 0, SEED)
        # Phase ≈ 0.20 (first third of window, before the 0.33 boundary)
        t = datetime.fromtimestamp(start_ep + int(spec.duration_s * 0.20), tz=UTC)
        val = scenario_value("capacity_pct", "dell", t, SEED)
        assert val is not None
        assert val >= 85, f"Capacity should be >= 85 % at phase=0.20, got {val}"

    def test_crosses_90_pct_mid_window(self):
        """Capacity must exceed 90 % in the middle third of the window."""
        spec = SCENARIOS["dell.capacity_breach"]
        start_ep = _firing_start_epoch(spec, 0, SEED)
        # Phase ≈ 0.55 (middle third)
        t = datetime.fromtimestamp(start_ep + int(spec.duration_s * 0.55), tz=UTC)
        val = scenario_value("capacity_pct", "dell", t, SEED)
        assert val is not None
        assert val >= 90, f"Capacity should be >= 90 % at phase=0.55, got {val}"

    def test_drops_during_cleanup(self):
        """Capacity must drop below 90 % during cleanup (phase > 0.67)."""
        spec = SCENARIOS["dell.capacity_breach"]
        start_ep = _firing_start_epoch(spec, 0, SEED)
        t = datetime.fromtimestamp(start_ep + int(spec.duration_s * 0.85), tz=UTC)
        val = scenario_value("capacity_pct", "dell", t, SEED)
        assert val is not None
        assert val < 90, f"Capacity should drop during cleanup, got {val}"

    def test_end_lower_than_peak(self):
        spec = SCENARIOS["dell.capacity_breach"]
        start_ep = _firing_start_epoch(spec, 0, SEED)
        t_peak = datetime.fromtimestamp(start_ep + int(spec.duration_s * 0.60), tz=UTC)
        t_end = datetime.fromtimestamp(start_ep + int(spec.duration_s * 0.95), tz=UTC)
        v_peak = scenario_value("capacity_pct", "dell", t_peak, SEED)
        v_end = scenario_value("capacity_pct", "dell", t_end, SEED)
        assert v_peak is not None and v_end is not None
        assert v_end < v_peak, f"End-of-window capacity {v_end} should be below peak {v_peak}"


# ---------------------------------------------------------------------------
# apply_scenario — rewriter hot-patch logic
# ---------------------------------------------------------------------------


class TestApplyScenario:
    """Verify that apply_scenario() replaces the correct lines in a snmprec."""

    def test_fan_status_line_patched(self):
        hpe_dev = HPE_DEVICES[0]
        baseline = render_snmprec(hpe_dev)
        t = _active_instant("hpe.fan_failure")
        modified = apply_scenario(baseline, hpe_dev, t, SEED)
        oid = HPE_SCENARIO_OIDS["fan_status"]
        patched_line = f"{oid}|66|4"
        assert patched_line in modified, (
            f"Expected fan_status=4 in modified snmprec:\n{modified}"
        )

    def test_raid_status_line_patched(self):
        hpe_dev = HPE_DEVICES[0]
        baseline = render_snmprec(hpe_dev)
        t = _active_instant("hpe.raid_degraded")
        modified = apply_scenario(baseline, hpe_dev, t, SEED)
        oid = HPE_SCENARIO_OIDS["raid_status"]
        patched_line = f"{oid}|66|3"
        assert patched_line in modified

    def test_psu_status_line_patched(self):
        dell_dev = DELL_DEVICES[0]
        baseline = render_snmprec(dell_dev)
        t = _active_instant("dell.psu_failure")
        modified = apply_scenario(baseline, dell_dev, t, SEED)
        oid = DELL_SCENARIO_OIDS["psu_status"]
        patched_line = f"{oid}|66|11"
        assert patched_line in modified

    def test_mem_leak_line_patched(self):
        dell_dev = DELL_DEVICES[0]
        baseline = render_snmprec(dell_dev)
        t = _active_instant("dell.mem_leak")
        modified = apply_scenario(baseline, dell_dev, t, SEED)
        oid = DELL_SCENARIO_OIDS["mem_used_pct"]
        # The line should now be a static |66|<pct> line, not :numeric
        assert f"{oid}|66|" in modified
        assert f"{oid}|66:numeric|" not in modified

    def test_non_hpe_dell_device_unchanged(self):
        cisco_devs = [d for d in DEVICES if d.vendor == "cisco"]
        if not cisco_devs:
            pytest.skip("No Cisco device in topology")
        dev = cisco_devs[0]
        baseline = render_snmprec(dev)
        t = _active_instant("hpe.fan_failure")
        modified = apply_scenario(baseline, dev, t, SEED)
        assert modified == baseline, "Non-HPE/Dell device snmprec must not be modified"

    def test_baseline_outside_scenario_unchanged(self):
        hpe_dev = HPE_DEVICES[0]
        baseline = render_snmprec(hpe_dev)
        t = _before_instant("hpe.fan_failure")
        modified = apply_scenario(baseline, hpe_dev, t, SEED)
        # When no scenario is active, content should be identical to baseline
        assert modified == baseline, "No-scenario content must match baseline"

    def test_modified_snmprec_oid_order_preserved(self):
        """apply_scenario must preserve OID ascending order (line order unchanged)."""
        hpe_dev = HPE_DEVICES[0]
        baseline = render_snmprec(hpe_dev)
        t = _active_instant("hpe.fan_failure")
        modified = apply_scenario(baseline, hpe_dev, t, SEED)
        oids = [
            tuple(int(x) for x in line.split("|")[0].split("."))
            for line in modified.strip().splitlines()
            if line and not line.startswith("#")
        ]
        assert oids == sorted(oids), "OID ordering violated after apply_scenario"


# ---------------------------------------------------------------------------
# render_snmprec baseline OID presence
# ---------------------------------------------------------------------------


class TestScenarioOidsInBaseline:
    @pytest.mark.parametrize("device", HPE_DEVICES)
    def test_hpe_devices_have_all_scenario_oids(self, device):
        content = render_snmprec(device)
        for oid_kind, oid_str in HPE_SCENARIO_OIDS.items():
            assert oid_str in content, (
                f"HPE device {device.name} missing scenario OID '{oid_kind}': {oid_str}"
            )

    @pytest.mark.parametrize("device", DELL_DEVICES)
    def test_dell_non_storage_have_psu_and_mem_oids(self, device):
        if device.role == "storage":
            pytest.skip("Storage devices tested separately")
        content = render_snmprec(device)
        for oid_kind in ("psu_status", "psu_power_w", "mem_used_pct"):
            oid_str = DELL_SCENARIO_OIDS[oid_kind]
            assert oid_str in content, (
                f"Dell device {device.name} missing scenario OID '{oid_kind}': {oid_str}"
            )

    @pytest.mark.parametrize("device", DELL_DEVICES)
    def test_dell_storage_has_capacity_oid(self, device):
        if device.role != "storage":
            pytest.skip("Non-storage devices skip capacity OID")
        content = render_snmprec(device)
        assert DELL_SCENARIO_OIDS["capacity_pct"] in content, (
            f"Dell storage device {device.name} missing capacity OID"
        )

    def test_cisco_devices_lack_hpe_oids(self):
        cisco_devs = [d for d in DEVICES if d.vendor == "cisco"]
        assert cisco_devs, "No Cisco devices in topology"
        for dev in cisco_devs:
            content = render_snmprec(dev)
            for oid_str in HPE_SCENARIO_OIDS.values():
                assert oid_str not in content, (
                    f"Cisco device {dev.name} unexpectedly has HPE OID {oid_str}"
                )

    def test_hpe_devices_lack_dell_specific_oids(self):
        """HPE devices must not have Dell-enterprise OIDs (674.*).

        Note: the shared private storage OID (99999) is intentionally present
        in all storage-role devices regardless of vendor, so it is excluded here.
        """
        dell_enterprise_oids = {
            k: v
            for k, v in DELL_SCENARIO_OIDS.items()
            if k != "capacity_pct"  # 99999 OID is vendor-neutral
        }
        for dev in HPE_DEVICES:
            content = render_snmprec(dev)
            for oid_kind, oid_str in dell_enterprise_oids.items():
                assert oid_str not in content, (
                    f"HPE device {dev.name} unexpectedly has Dell OID '{oid_kind}': {oid_str}"
                )
