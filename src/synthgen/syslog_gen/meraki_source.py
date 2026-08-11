"""Cisco Meraki syslog generator.

Emits syslog lines for Meraki devices found in the topology (vendor_os=meraki):

  meraki-mx-01  (role=firewall) — flows and urls
  meraki-ap-01  (role=ap)       — client association / disassociation events
  meraki-ap-02  (role=ap)       — client association / disassociation events

Rates are scaled by the ``user`` diurnal pattern via :func:`rate_multiplier`.
Client MACs are deterministic per device + minute-bucket + client index so the
same logical client stays associated across consecutive ticks.
"""
from __future__ import annotations

import random
from datetime import datetime

from synthgen import GLOBAL_SEED
from synthgen.common.patterns import rate_multiplier
from synthgen.common.scenarios import active_scenarios
from synthgen.common.topology import Topology
from synthgen.syslog_gen.formats import meraki

# Peak flows+urls per second per MX device (scaled by rate_multiplier).
PEAK_FLOWS_PER_SEC = 4
# Peak events per second per AP device.
PEAK_EVENTS_PER_SEC = 2

_EXTERNAL_NET = "203.0.113."
_URL_METHODS = ["GET", "POST"]
_URL_PATHS = [
    "https://update.example.com/check",
    "https://cdn.example.com/asset.js",
    "https://api.example.com/v1/data",
    "https://auth.example.com/oauth/token",
]


def _wifi_client_mac(device_name: str, bucket: int, client_idx: int, seed: int) -> str:
    """Deterministic unicast MAC per device + minute-bucket + client index."""
    rng = random.Random(f"{seed}|mac|{device_name}|{bucket}|{client_idx}")
    octets = [rng.randint(0, 255) for _ in range(6)]
    octets[0] &= 0xFE  # force unicast (clear multicast bit)
    return ":".join(f"{o:02X}" for o in octets)


def _scenario_serial(device_name: str) -> str:
    """Deterministic fake serial number derived from device name."""
    h = 5381
    for c in device_name.encode():
        h = ((h << 5) + h + c) & 0xFFFFFF
    return f"Q2KD-{h:06X}"


def generate_batch(topo: Topology, t: datetime, seed: int = GLOBAL_SEED) -> list[str]:
    """Return Meraki syslog lines for one 1-second tick.

    The function is pure: identical ``(topo, t, seed)`` always produces the
    same output list.
    """
    lines: list[str] = []
    minute_bucket = int(t.timestamp()) // 60

    for dev in topo.devices_by_vendor_os("meraki"):
        rng = random.Random(f"{seed}|{dev.name}|{int(t.timestamp())}")

        if dev.role == "firewall":
            # MX: emit flow and url records
            mult = rate_multiplier(t, "user", f"meraki:{dev.name}", seed)
            n = int(PEAK_FLOWS_PER_SEC * mult) + (
                1 if rng.random() < (PEAK_FLOWS_PER_SEC * mult) % 1 else 0
            )
            servers = [d for d in topo.devices if d.site == dev.site and d.role == "server"]
            for _ in range(n):
                src_ip = _EXTERNAL_NET + str(rng.randint(2, 254))
                src_port = rng.randint(1024, 65000)
                dst = rng.choice(servers) if servers else dev
                dst_port = rng.choice([80, 443, 8080, 8443])
                if rng.random() < 0.6:
                    lines.append(
                        meraki.meraki_flow(t, dev.name, src_ip, src_port, dst.ip, dst_port)
                    )
                else:
                    mac = _wifi_client_mac(dev.name, minute_bucket, rng.randint(0, 19), seed)
                    method = rng.choice(_URL_METHODS)
                    url = rng.choice(_URL_PATHS)
                    lines.append(
                        meraki.meraki_url(
                            t, dev.name, src_ip, src_port, dst.ip, dst_port,
                            mac, method, url,
                        )
                    )

        elif dev.role == "ap":
            # MR AP: emit association / disassociation events
            mult = rate_multiplier(t, "user", f"meraki:{dev.name}", seed)
            n = int(PEAK_EVENTS_PER_SEC * mult) + (
                1 if rng.random() < (PEAK_EVENTS_PER_SEC * mult) % 1 else 0
            )
            radio = rng.randint(0, 1)
            vap = rng.randint(0, 3)
            for _ in range(n):
                client_mac = _wifi_client_mac(dev.name, minute_bucket, rng.randint(0, 9), seed)
                if rng.random() < 0.7:
                    lines.append(
                        meraki.meraki_event_association(t, dev.name, radio, vap, client_mac)
                    )
                else:
                    lines.append(
                        meraki.meraki_event_disassociation(t, dev.name, radio, vap, client_mac)
                    )

        # ── Scenario overlay (separate RNG; does not touch baseline rng) ──────
        sc = active_scenarios("meraki", t, seed)
        if not sc:
            continue

        aps = [d for d in topo.devices_by_vendor_os("meraki") if d.role == "ap"]

        for spec, ph in sc:
            elapsed = ph * spec.duration_s
            remaining = spec.duration_s - elapsed

            if spec.id == "meraki.ap_offline":
                # Device down/up events reported by the MX.
                if dev.role != "firewall":
                    continue
                if not aps:
                    continue
                ap_rng = random.Random(f"{seed}|{spec.id}|target")
                target_ap = aps[ap_rng.randint(0, len(aps) - 1)]
                serial = _scenario_serial(target_ap.name)
                if remaining > spec.duration_s * 0.1:
                    lines.append(meraki.meraki_event_device_down(
                        t, dev.name, target_ap.name, serial
                    ))
                else:
                    lines.append(meraki.meraki_event_device_up(
                        t, dev.name, target_ap.name, serial
                    ))

            elif spec.id == "meraki.rogue_ap":
                # Air Marshal rogue-AP detection from each AP.
                if dev.role != "ap":
                    continue
                rogue_rng = random.Random(f"{seed}|{spec.id}|rogue")
                bssid_octets = [rogue_rng.randint(0, 255) for _ in range(6)]
                bssid = ":".join(f"{o:02X}" for o in bssid_octets)
                ssid = "FreePublicWiFi"
                rssi = -int(50 + ph * 20)  # signal attenuates over time
                lines.append(meraki.meraki_event_air_marshal(t, dev.name, bssid, ssid, rssi))

            elif spec.id == "meraki.wan_failover":
                # MX uplink-change event; primary goes down, secondary takes over.
                if dev.role != "firewall":
                    continue
                if remaining > spec.duration_s * 0.1:
                    # Failover: traffic on secondary uplink
                    lines.append(meraki.meraki_event_uplink_change(
                        t, dev.name, "wan2", "active", "203.0.113.51"
                    ))
                else:
                    # Recovery: primary uplink restored
                    lines.append(meraki.meraki_event_uplink_change(
                        t, dev.name, "wan1", "active", "203.0.113.50"
                    ))

    return lines
