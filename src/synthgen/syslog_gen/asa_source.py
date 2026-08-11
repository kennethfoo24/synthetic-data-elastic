from __future__ import annotations

import random
from datetime import datetime

from synthgen import GLOBAL_SEED
from synthgen.common.patterns import rate_multiplier
from synthgen.common.scenarios import active_scenarios
from synthgen.common.topology import Topology
from synthgen.syslog_gen.formats import asa

# Peak-hour message rate per ASA device, scaled by the pattern engine.
PEAK_MSGS_PER_SEC = 8
EXTERNAL_NET = "203.0.113."  # TEST-NET-3 for synthetic "internet" clients

# Scenario attacker net (RFC 5737 TEST-NET-2 — distinct from baseline EXTERNAL_NET).
_SCENARIO_NET = "198.51.100."


def generate_batch(topo: Topology, t: datetime, seed: int = GLOBAL_SEED) -> list[str]:
    lines: list[str] = []
    for dev in topo.devices_by_vendor_os("asa"):
        # ── Baseline (unchanged; RNG state is identical to pre-scenario code) ──
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
                dur = f"0:{rng.randint(0, 9):02d}:{rng.randint(10, 59):02d}"
                lines.append(asa.asa_302014(t, dev.name, conn_id, src_ip, src_port, dst.ip, 443,
                                            duration=dur, byte_count=rng.randint(500, 2_000_000)))
            elif roll < 0.97:
                lines.append(asa.asa_106023(t, dev.name, src_ip, src_port, dst.ip,
                                            rng.choice([22, 23, 3389, 445])))
            else:
                lines.append(asa.asa_113005(t, dev.name, f"user{rng.randint(1, 40)}", src_ip))

        # ── Scenario overlay (separate RNG; does not touch baseline rng) ──────
        sc = active_scenarios("asa", t, seed)
        if not sc:
            continue

        sc_rng = random.Random(f"{seed}|asa|sc|{dev.name}|{int(t.timestamp())}")

        for spec, ph in sc:
            if spec.id == "asa.brute_force":
                # Burst of asa_113005 from one fixed attacker IP.
                # Intensity peaks at mid-window (tent function).
                atk_rng = random.Random(f"{seed}|{spec.id}|attacker")
                attacker_ip = _SCENARIO_NET + str(atk_rng.randint(2, 50))
                intensity = min(ph, 1.0 - ph) * 2  # 0 → 1 → 0
                n_extra = max(1, int(15 * intensity))
                for _ in range(n_extra):
                    user = f"svc{sc_rng.randint(1, 5)}"
                    lines.append(asa.asa_113005(t, dev.name, user, attacker_ip))

            elif spec.id == "asa.conn_storm":
                # Storm of 302013/302014/106023 from one fixed IP; builds over time.
                storm_rng = random.Random(f"{seed}|{spec.id}|storm")
                storm_ip = _SCENARIO_NET + str(storm_rng.randint(51, 200))
                n_extra = max(2, int(25 * ph))
                for _ in range(n_extra):
                    conn_id = sc_rng.randint(100_000, 999_999)
                    dst = sc_rng.choice(targets) if targets else dev
                    sport = sc_rng.randint(1024, 65000)
                    roll = sc_rng.random()
                    if roll < 0.50:
                        lines.append(asa.asa_302013(t, dev.name, conn_id, storm_ip, sport, dst.ip, 80))
                    elif roll < 0.80:
                        lines.append(asa.asa_302014(t, dev.name, conn_id, storm_ip, sport, dst.ip, 80,
                                                    duration="0:00:01", byte_count=1024))
                    else:
                        lines.append(asa.asa_106023(t, dev.name, storm_ip, sport, dst.ip, 80))

            elif spec.id == "asa.failover":
                # Failover syslogs: secondary active during most of window,
                # then primary resumes at the very end.
                elapsed = ph * spec.duration_s
                remaining = spec.duration_s - elapsed
                if remaining > spec.duration_s * 0.1:
                    # Secondary is ACTIVE — failover in progress
                    lines.append(asa.asa_104001(t, dev.name, unit="Secondary"))
                else:
                    # Primary resumes ACTIVE — failback
                    lines.append(asa.asa_104002(t, dev.name, unit="Primary"))

    return lines
