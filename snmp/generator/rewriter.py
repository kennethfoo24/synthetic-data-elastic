"""
Scenario rewriter — continuously re-renders HPE/Dell .snmprec files with
scenario-adjusted values during active scenario windows.

snmpsim hot-reloads .snmprec files on every incoming SNMP request (no process
restart needed), so overwriting a file immediately changes the values served.
Empirically confirmed: a static Gauge32 value changed from 42 to 99 was
reflected on the very next snmpget without restarting snmpsim.

Usage
-----
# Standalone (from project root):
    .venv/bin/python snmp/generator/rewriter.py --seed 42

# Single render pass (for testing):
    .venv/bin/python snmp/generator/rewriter.py --seed 42 --once

# In K8s sidecar — see k8s/generators/snmpsim.yaml for the full pod spec.
"""
from __future__ import annotations

import argparse
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

# Ensure the project root is on sys.path when run as a script from any cwd.
_PROJECT_ROOT = Path(__file__).parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from snmp.generator.render import DATA_DIR, _snmp_devices, render_snmprec
from snmp.generator.scenario_values import (
    DELL_SCENARIO_OIDS,
    HPE_SCENARIO_OIDS,
    scenario_value,
)
from synthgen.common.topology import Device

# ---------------------------------------------------------------------------
# Core logic
# ---------------------------------------------------------------------------


def apply_scenario(content: str, device: Device, t: datetime, seed: int) -> str:
    """Return .snmprec content with scenario values substituted where active.

    For each scenario OID that belongs to *device.vendor*, if a scenario is
    firing at *t* the corresponding line is replaced with a static
    ``OID|66|VALUE`` line.  Lines for OIDs with no active scenario are left
    unchanged, preserving the baseline numeric-variation behaviour.

    Parameters
    ----------
    content:
        Baseline .snmprec content from :func:`render_snmprec`.
    device:
        The device whose file is being rewritten.
    t:
        Timezone-aware instant at which to evaluate active scenarios.
    seed:
        Scenario schedule seed (must be consistent across all callers).
    """
    if device.vendor not in ("hpe", "dell"):
        return content

    oid_map = HPE_SCENARIO_OIDS if device.vendor == "hpe" else DELL_SCENARIO_OIDS
    result: list[str] = []
    for line in content.splitlines():
        substituted = False
        for oid_kind, oid_str in oid_map.items():
            if line.startswith(oid_str + "|"):
                val = scenario_value(oid_kind, device.vendor, t, seed)
                if val is not None:
                    result.append(f"{oid_str}|66|{val}")
                    substituted = True
                break  # each line matches at most one OID
        if not substituted:
            result.append(line)
    return "\n".join(result) + "\n"


def rewrite_once(
    devices: list[Device],
    data_dir: Path,
    seed: int,
    *,
    t: datetime | None = None,
) -> dict[str, bool]:
    """Render scenario-aware .snmprec files for all HPE and Dell devices.

    Returns a mapping of ``device_name → changed`` indicating which files
    were actually written (content differed from the previous version).

    Parameters
    ----------
    devices:
        Full device list from topology (non-database, non-meraki).
    data_dir:
        Directory containing .snmprec files (must already exist).
    seed:
        Scenario schedule seed.
    t:
        Override the query instant (default: current UTC time).  Useful for
        deterministic testing and backfill simulation.
    """
    if t is None:
        t = datetime.now(UTC)

    changed: dict[str, bool] = {}
    for device in devices:
        if device.vendor not in ("hpe", "dell"):
            continue
        baseline = render_snmprec(device)
        modified = apply_scenario(baseline, device, t, seed)
        path = data_dir / f"{device.name}.snmprec"
        current = path.read_text() if path.exists() else ""
        if current != modified:
            path.write_text(modified)
            changed[device.name] = True
        else:
            changed[device.name] = False
    return changed


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="SNMP scenario rewriter — hot-patches .snmprec files as "
                    "scenario windows open and close."
    )
    parser.add_argument(
        "--seed", type=int, required=True,
        help="Scenario schedule seed (must match other generators)"
    )
    parser.add_argument(
        "--interval", type=int, default=60,
        help="Re-render interval in seconds (default: 60)"
    )
    parser.add_argument(
        "--data-dir", type=Path, default=DATA_DIR,
        help="Path to snmpsim data directory (default: snmp/data/)"
    )
    parser.add_argument(
        "--once", action="store_true",
        help="Render once then exit (useful for smoke-testing)"
    )
    args = parser.parse_args()

    devices = _snmp_devices()
    hpe_dell = [d for d in devices if d.vendor in ("hpe", "dell")]
    print(
        f"[rewriter] seed={args.seed} interval={args.interval}s "
        f"data-dir={args.data_dir} devices={len(hpe_dell)}"
    )

    if args.once:
        changed = rewrite_once(devices, args.data_dir, args.seed)
        written = [n for n, c in changed.items() if c]
        print(f"[rewriter] wrote {len(written)} files: {written}")
        return

    while True:
        changed = rewrite_once(devices, args.data_dir, args.seed)
        written = [n for n, c in changed.items() if c]
        if written:
            print(f"[rewriter] {datetime.now(UTC).isoformat()} updated: {written}")
        time.sleep(args.interval)


if __name__ == "__main__":
    main()
