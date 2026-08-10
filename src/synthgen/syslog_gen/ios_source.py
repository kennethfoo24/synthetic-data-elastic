from __future__ import annotations

import random
from datetime import datetime

from synthgen import GLOBAL_SEED
from synthgen.common.patterns import rate_multiplier
from synthgen.common.topology import Topology
from synthgen.syslog_gen.formats import ios

# Peak-hour message rate per IOS device, scaled by the pattern engine.
PEAK_MSGS_PER_SEC = 2

# Sequence counter epoch: 2023-11-14 UTC.  All seq numbers are positive offsets
# from this base, derived purely from wall-clock time — no module state.
_EPOCH_BASE = 1_700_000_000
# Max messages we can emit per tick per device; keeps seq lanes non-overlapping.
_SEQ_STRIDE = 20


def _seq(t: datetime, device_idx: int, msg_idx: int) -> int:
    """Deterministic per-device sequence number derived purely from time."""
    return (int(t.timestamp()) - _EPOCH_BASE) * _SEQ_STRIDE + device_idx * 3 + msg_idx


def generate_batch(topo: Topology, t: datetime, seed: int = GLOBAL_SEED) -> list[str]:
    lines: list[str] = []
    ios_devices = topo.devices_by_vendor_os("ios")
    for dev_idx, dev in enumerate(ios_devices):
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
    return lines
