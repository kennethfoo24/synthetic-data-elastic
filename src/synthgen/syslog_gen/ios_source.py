from __future__ import annotations

import random
from datetime import datetime

from synthgen import GLOBAL_SEED
from synthgen.common.patterns import rate_multiplier
from synthgen.common.scenarios import active_scenarios
from synthgen.common.topology import Topology
from synthgen.syslog_gen.formats import ios

# Peak-hour message rate per IOS device, scaled by the pattern engine.
PEAK_MSGS_PER_SEC = 2

# Sequence counter epoch: 2023-11-14 UTC.  All seq numbers are positive offsets
# from this base, derived purely from wall-clock time — no module state.
_EPOCH_BASE = 1_700_000_000
# Max messages we can emit per tick per device; keeps seq lanes non-overlapping.
_SEQ_STRIDE = 20

# Scenario STP states (used by ios.stp_reconverge).
_STP_STATES = ["Listening", "Learning", "Forwarding"]

# Scenario CPU processes (used by ios.cpu_spike).
_CPU_PROCESSES = ["IP Input", "CEF process", "OSPF", "BGP Scanner"]


def _seq(t: datetime, device_idx: int, msg_idx: int) -> int:
    """Deterministic per-device sequence number derived purely from time."""
    return (int(t.timestamp()) - _EPOCH_BASE) * _SEQ_STRIDE + device_idx * 3 + msg_idx


def _sc_seq(t: datetime, device_idx: int, sc_msg_idx: int) -> int:
    """Deterministic sequence number for scenario overlay messages.

    Uses a separate multiplied range so scenario seqs never clash with baseline.
    """
    return (int(t.timestamp()) - _EPOCH_BASE) * _SEQ_STRIDE * 10 + device_idx * 20 + sc_msg_idx


def generate_batch(topo: Topology, t: datetime, seed: int = GLOBAL_SEED) -> list[str]:
    lines: list[str] = []
    ios_devices = topo.devices_by_vendor_os("ios")
    for dev_idx, dev in enumerate(ios_devices):
        # ── Baseline (unchanged; RNG state identical to pre-scenario code) ────
        mult = rate_multiplier(t, "user", f"ios:{dev.name}", seed)
        rng = random.Random(f"{seed}|{dev.name}|{int(t.timestamp())}")
        n = int(PEAK_MSGS_PER_SEC * mult) + (
            1 if rng.random() < (PEAK_MSGS_PER_SEC * mult) % 1 else 0
        )
        for i in range(n):
            seq = _seq(t, dev_idx, i)
            roll = rng.random()
            if roll < 0.45:
                user = f"admin{rng.randint(1, 5)}"
                src_ip = (
                    f"10.{rng.randint(1, 20)}.{rng.randint(1, 254)}"
                    f".{rng.randint(1, 254)}"
                )
                lines.append(ios.ios_login_success(t, dev.name, seq, user, src_ip))
            elif roll < 0.80:
                user = f"netops{rng.randint(1, 3)}"
                lines.append(ios.ios_config_i(t, dev.name, seq, user))
            elif roll < 0.98:
                host = f"10.{rng.randint(1, 5)}.0.{rng.randint(1, 10)}"
                lines.append(ios.ios_logginghost(t, dev.name, seq, host))
            elif roll < 0.99:
                # rare: link state change
                iface = f"GigabitEthernet{rng.randint(0, 3)}/{rng.randint(0, 23)}"
                state = rng.choice(["up", "down"])
                lines.append(ios.ios_link_updown(t, dev.name, seq, state, iface))
            else:
                # rare: line protocol change
                iface = f"GigabitEthernet{rng.randint(0, 3)}/{rng.randint(0, 23)}"
                state = rng.choice(["up", "down"])
                lines.append(ios.ios_lineproto_updown(t, dev.name, seq, state, iface))

        # ── Scenario overlay (separate RNG; does not touch baseline rng) ──────
        sc = active_scenarios("ios", t, seed)
        if not sc:
            continue

        for spec, ph in sc:
            elapsed = ph * spec.duration_s  # seconds into the firing window

            if spec.id == "ios.intf_flap":
                # LINK-3-UPDOWN + LINEPROTO-5-UPDOWN on one fixed interface.
                # Flaps alternate down/up every 30 s.
                iface_rng = random.Random(f"{seed}|{spec.id}|{dev.name}|iface")
                flap_iface = f"GigabitEthernet{iface_rng.randint(0, 1)}/{iface_rng.randint(1, 3)}"
                if int(elapsed) % 30 == 0:
                    flap_num = int(elapsed) // 30
                    state = "down" if flap_num % 2 == 0 else "up"
                    seq0 = _sc_seq(t, dev_idx, 0)
                    seq1 = _sc_seq(t, dev_idx, 1)
                    lines.append(ios.ios_link_updown(t, dev.name, seq0, state, flap_iface))
                    lines.append(ios.ios_lineproto_updown(t, dev.name, seq1, state, flap_iface))

            elif spec.id == "ios.stp_reconverge":
                # STP topology-change notification + port-state message every 15 s.
                stp_rng = random.Random(f"{seed}|{spec.id}|{dev.name}|stp")
                vlan = stp_rng.randint(1, 100)
                stp_iface = f"GigabitEthernet{stp_rng.randint(0, 1)}/{stp_rng.randint(1, 12)}"
                if int(elapsed) % 15 == 0:
                    state_idx = (int(elapsed) // 15) % len(_STP_STATES)
                    seq0 = _sc_seq(t, dev_idx, 2)
                    seq1 = _sc_seq(t, dev_idx, 3)
                    lines.append(ios.ios_stp_topology_change(t, dev.name, seq0, vlan, stp_iface))
                    lines.append(ios.ios_stp_portstatus(t, dev.name, seq1, stp_iface, _STP_STATES[state_idx]))

            elif spec.id == "ios.cpu_spike":
                # CPUHOG on every tick; CPU% ramps from 70 → 95 over the window.
                cpu_rng = random.Random(f"{seed}|{spec.id}|{dev.name}|cpu")
                process = cpu_rng.choice(_CPU_PROCESSES)
                cpu_pct = min(99, int(70 + ph * 25))
                seq0 = _sc_seq(t, dev_idx, 4)
                lines.append(ios.ios_cpu_threshold(t, dev.name, seq0, process, cpu_pct))

    return lines
