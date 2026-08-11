# Cisco Meraki Scenarios

Data streams: `logs-cisco_meraki.log-default` (flows/urls), `logs-cisco_meraki.events-default` (events)
Source devices: `meraki-mx-01` (MX250 firewall, `10.10.3.1`), `meraki-ap-01`, `meraki-ap-02` (MR46 APs)

---

## meraki.ap_offline — Access point offline

**Schedule:** Every 3h ± up to 45 min. Duration: ~15 minutes (900 s).

**What happens:** The MX firewall reports a target access point as unreachable by emitting `type=device_down` events continuously for 90% of the window. In the final 10% (approximately the last 90 seconds), a `type=device_up` event is emitted indicating the AP is back online. The target AP is deterministically selected per seed.

**Data touched:**
- Data stream: `logs-cisco_meraki.events-default`
- `cisco.meraki.event_type`: `"device_down"` — emitted once per second for ~13.5 min; never appears in baseline Meraki events
- `cisco.meraki.event_type`: `"device_up"` — emitted in the final ~1.5 min of the window
- `cisco.meraki.device_name`: name of the targeted AP (e.g., `"meraki-ap-02"`) — fixed per scenario firing
- `cisco.meraki.device_serial`: deterministic serial derived from the AP name (e.g., `"Q2KD-0000-0002"`)
- `observer.hostname`: `"meraki-mx-01"` — the MX that reports the AP state (only the MX emits device events)

**Where to see it:**
- Dashboard: `synthnet-network-overview` — `device_down` events visible in the Meraki events panel; a sustained stream of device_down followed by a single device_up is the visual pattern
- ES query: `GET /logs-cisco_meraki.events-default/_search?q=cisco.meraki.event_type:device_down&size=10`

**Scenario markers** (fields/values that confirm it's active):
- `cisco.meraki.event_type: "device_down"` — this event type is absent from baseline Meraki traffic
- `observer.hostname: "meraki-mx-01"` with `cisco.meraki.event_type: "device_down"` occurring more than once in a 5-minute window

---

## meraki.rogue_ap — Rogue access point detected

**Schedule:** Every 3h ± up to 45 min. Duration: ~12 minutes (720 s).

**What happens:** Each Meraki AP emits Air Marshal rogue-AP detection events once per second, reporting a fixed rogue BSSID with SSID `FreePublicWiFi`. The RSSI (signal strength) attenuates over the window, starting at approximately -50 dBm and reaching -70 dBm by the end, simulating the rogue AP drifting further away or being suppressed.

**Data touched:**
- Data stream: `logs-cisco_meraki.events-default`
- `cisco.meraki.event_type`: `"air_marshal_detected"` — never appears in baseline Meraki events
- `cisco.meraki.wireless.bssid`: a fixed rogue BSSID (hex MAC, deterministic per seed, e.g., `"A1:B2:C3:D4:E5:F6"`)
- `cisco.meraki.wireless.ssid`: `"FreePublicWiFi"` — fixed value; no legitimate AP uses this SSID in the topology
- `cisco.meraki.wireless.rssi`: integer starting near `-50` and decreasing to `-70` over the 12-minute window
- `observer.hostname`: one of `"meraki-ap-01"` or `"meraki-ap-02"` — only APs emit Air Marshal events

**Where to see it:**
- Dashboard: `synthnet-network-overview` — Air Marshal events in the Meraki events panel; RSSI trend visible over the 12-minute window
- ES query: `GET /logs-cisco_meraki.events-default/_search?q=cisco.meraki.event_type:air_marshal_detected&size=10`

**Scenario markers** (fields/values that confirm it's active):
- `cisco.meraki.event_type: "air_marshal_detected"` — unique to this scenario, absent from baseline
- `cisco.meraki.wireless.ssid: "FreePublicWiFi"` — no legitimate device in the topology uses this SSID
- `cisco.meraki.wireless.rssi` decreasing monotonically over successive events

---

## meraki.wan_failover — WAN uplink failover

**Schedule:** Every 3h ± up to 45 min. Duration: ~30 minutes (1800 s).

**What happens:** The MX firewall emits `type=uplink_change` events showing traffic switching to `wan2` (secondary uplink, `203.0.113.51`) for 90% of the window. In the final 10% (approximately the last 3 minutes), a `type=uplink_change` event restores `wan1` (primary, `203.0.113.50`) as the active uplink, simulating a WAN failover and recovery.

**Data touched:**
- Data stream: `logs-cisco_meraki.events-default`
- `cisco.meraki.event_type`: `"uplink_change"` — never present in baseline Meraki events
- `cisco.meraki.uplink.interface`: `"wan2"` during failover (90% of window); `"wan1"` during recovery (10%)
- `cisco.meraki.uplink.status`: `"active"` — both failover and recovery events set the specified interface to active
- `cisco.meraki.uplink.ip`: `"203.0.113.51"` (wan2 / failover) or `"203.0.113.50"` (wan1 / recovery)
- `observer.hostname`: `"meraki-mx-01"` — only the MX firewall emits uplink events

**Where to see it:**
- Dashboard: `synthnet-network-overview` — uplink_change events in the Meraki panel; wan2 active followed by wan1 recovery at the 27-minute mark is the pattern
- ES query: `GET /logs-cisco_meraki.events-default/_search?q=cisco.meraki.event_type:uplink_change&size=10`

**Scenario markers** (fields/values that confirm it's active):
- `cisco.meraki.event_type: "uplink_change"` — this event type is absent from all baseline Meraki traffic
- `cisco.meraki.uplink.interface: "wan2"` with `cisco.meraki.uplink.status: "active"` — primary is always wan1 at baseline
