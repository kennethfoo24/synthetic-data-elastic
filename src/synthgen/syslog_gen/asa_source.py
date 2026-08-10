from __future__ import annotations

import random
from datetime import datetime

from synthgen import GLOBAL_SEED
from synthgen.common.patterns import rate_multiplier
from synthgen.common.topology import Topology
from synthgen.syslog_gen.formats import asa

# Peak-hour message rate per ASA device, scaled by the pattern engine.
PEAK_MSGS_PER_SEC = 8
EXTERNAL_NET = "203.0.113."  # TEST-NET-3 for synthetic "internet" clients


def generate_batch(topo: Topology, t: datetime, seed: int = GLOBAL_SEED) -> list[str]:
    lines: list[str] = []
    for dev in topo.devices_by_vendor_os("asa"):
        mult = rate_multiplier(t, "user", f"asa:{dev.name}", seed)
        rng = random.Random(f"{seed}|{dev.name}|{int(t.timestamp())}")
        n = int(PEAK_MSGS_PER_SEC * mult) + (1 if rng.random() < (PEAK_MSGS_PER_SEC * mult) % 1 else 0)
        # inside targets: servers/databases in the same site as the ASA
        targets = [d for d in topo.devices if d.site == dev.site and d.role in ("server", "database")]
        for _ in range(n):
            src_ip = EXTERNAL_NET + str(rng.randint(2, 254))
            src_port = rng.randint(1024, 65000)
            dst = rng.choice(targets)
            conn_id = rng.randint(10_000, 999_999)
            roll = rng.random()
            if roll < 0.45:
                lines.append(asa.asa_302013(t, dev.name, conn_id, src_ip, src_port, dst.ip, 443))
            elif roll < 0.85:
                dur = f"0:{rng.randint(0, 9)}:{rng.randint(10, 59)}"
                lines.append(asa.asa_302014(t, dev.name, conn_id, src_ip, src_port, dst.ip, 443,
                                            duration=dur, byte_count=rng.randint(500, 2_000_000)))
            elif roll < 0.97:
                lines.append(asa.asa_106023(t, dev.name, src_ip, src_port, dst.ip,
                                            rng.choice([22, 23, 3389, 445])))
            else:
                lines.append(asa.asa_113005(t, dev.name, f"user{rng.randint(1, 40)}", src_ip))
    return lines
