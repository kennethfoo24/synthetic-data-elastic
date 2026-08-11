# Cisco IOS Scenarios

Data stream: `logs-cisco_ios.log-default`
Source devices: `cisco-rtr-core-01`, `cisco-rtr-core-02` (ISR4451), `cisco-sw-access-01/02/03` (C9300-48T), `cisco-rtr-dr`, `cisco-sw-dr-01`

---

## ios.intf_flap — Interface flapping

**Schedule:** Every 3h ± up to 45 min. Duration: ~6 minutes (360 s).

**What happens:** A deterministically chosen GigabitEthernet interface on each IOS device alternates between down and up states every 30 seconds, emitting paired LINK and LINEPROTO syslog messages. Over the 6-minute window this produces approximately 12 down/up cycles per device, simulating a flapping physical link.

**Data touched:**
- Data stream: `logs-cisco_ios.log-default`
- `event.code`: `"UPDOWN"` — mnemonic for both `LINK-3-UPDOWN` and `LINEPROTO-5-UPDOWN`; baseline also emits UPDOWN but rarely (< 1%)
- `cisco.ios.facility`: `"LINK"` and `"LINEPROTO"` — the specific facilities that appear on every 30-second cycle
- `log.level`: `"error"` (IOS severity 3) for LINK; `"notification"` (severity 5) for LINEPROTO
- `message`: contains `"Interface GigabitEthernet{slot}/{port}, changed state to down"` and `"...to up"` alternating every 30 s
- Sequence number: increments on a fixed stride — scenario messages use a separate multiplied stride that does not collide with baseline sequence lanes

**Where to see it:**
- Dashboard: `synthnet-network-overview` — LINK-3-UPDOWN event count spikes during the window; repeated down/up pairs on the same interface name are the visual pattern
- ES query: `GET /logs-cisco_ios.log-default/_search?q=event.code:UPDOWN+AND+cisco.ios.facility:LINK&size=10`

**Scenario markers** (fields/values that confirm it's active):
- `cisco.ios.facility: "LINK"` with `event.code: "UPDOWN"` at 2-per-30-s cadence — baseline LINK-UPDOWN events are sporadic (< 1 per hour per device)
- Same `message` interface name repeating on alternating down/up pairs within a 6-minute window

---

## ios.stp_reconverge — Spanning Tree Protocol reconvergence

**Schedule:** Every 3h ± up to 45 min. Duration: ~5 minutes (300 s).

**What happens:** A single VLAN and interface pair are chosen deterministically per device. Every 15 seconds, the device emits a SPANTREE-2-TOPOLOGY_CHANGE notification followed by a SPANTREE-7-PORTSTATUS event cycling through the STP states: Listening → Learning → Forwarding. This simulates an STP topology change causing network reconvergence.

**Data touched:**
- Data stream: `logs-cisco_ios.log-default`
- `event.code`: `"TOPOLOGY_CHANGE"` — never present in baseline traffic; appears every 15 s during the window
- `event.code`: `"PORTSTATUS"` — also absent in baseline; alternates with TOPOLOGY_CHANGE every 15 s
- `cisco.ios.facility`: `"SPANTREE"` — the STP facility; baseline messages only use `SYS`, `LINK`, `LINEPROTO`, `SEC_LOGIN`
- `log.level`: `"critical"` (IOS severity 2) for TOPOLOGY_CHANGE; `"debug"` (severity 7) for PORTSTATUS
- `message`: `"VLAN{NNNN} [port GigabitEthernet{n}/{n}] topology changed"` — VLAN ID and port fixed per device for the window

**Where to see it:**
- Dashboard: `synthnet-network-overview` — `SPANTREE` facility events appear in log table; TOPOLOGY_CHANGE + PORTSTATUS alternation at 15-second intervals is the pattern
- ES query: `GET /logs-cisco_ios.log-default/_search?q=cisco.ios.facility:SPANTREE&size=10`

**Scenario markers** (fields/values that confirm it's active):
- `cisco.ios.facility: "SPANTREE"` — this facility is absent from all baseline IOS traffic
- `event.code: "TOPOLOGY_CHANGE"` or `event.code: "PORTSTATUS"` — both unique to this scenario

---

## ios.cpu_spike — CPU process spike

**Schedule:** Every 3h ± up to 45 min. Duration: ~20 minutes (1200 s).

**What happens:** Each IOS device emits `%SYS-3-CPUHOG` messages once per second, with the reported CPU utilization ramping from 70% at the start of the window to 95% by the end (`cpu_pct = min(99, int(70 + phase * 25))`). The process name is drawn from: `IP Input`, `CEF process`, `OSPF`, `BGP Scanner`.

**Data touched:**
- Data stream: `logs-cisco_ios.log-default`
- `event.code`: `"CPUHOG"` — never emitted in baseline traffic
- `cisco.ios.facility`: `"SYS"` — same facility as baseline CONFIG_I and LOGGINGHOST_STARTSTOP, but with severity 3 vs. baseline severity 5/6
- `log.level`: `"error"` (IOS severity 3) — baseline SYS messages are severity 5 (`notification`) or 6 (`informational`)
- `message`: `"Task is running for 2 seconds or more, Process = {process}, CPU utilization {N}%"` — N climbs from 70 to 95 over the window

**Where to see it:**
- Dashboard: `synthnet-network-overview` — SYS-3-CPUHOG events visible in log table; CPU % field in message body increases monotonically over the 20-minute window
- ES query: `GET /logs-cisco_ios.log-default/_search?q=event.code:CPUHOG&size=20`

**Scenario markers** (fields/values that confirm it's active):
- `event.code: "CPUHOG"` — this mnemonic is absent from all baseline IOS traffic
- `message` contains `"CPU utilization"` with a value ≥ 70% — baseline `SYS` messages are CONFIG_I and LOGGINGHOST_STARTSTOP (no CPU percent)
