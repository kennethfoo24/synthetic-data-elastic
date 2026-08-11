# Palo Alto Networks (panw) Scenarios

Data stream: `logs-panw.panos-default`
Source device: `palo-fw-prod` (serial `001901000001`, model PA-3260, `10.10.0.1`)

---

## panw.port_scan — External port scan

**Schedule:** Every 3h ± up to 45 min. Duration: ~10 minutes (600 s).

**What happens:** A fixed attacker IP in `198.51.100.0/24` sends a dense burst of TCP probes to sequential destination ports on the first production server. The firewall logs 5–20 THREAT/deny records per second, with the scan rate tapering off over the window.

**Data touched:**
- Data stream: `logs-panw.panos-default`
- `panw.panos.type`: `"THREAT"` — appears only during this scenario (vs. baseline `"TRAFFIC"`)
- `panw.panos.subtype`: `"vulnerability"` — scan packets are classified as vulnerability attempts
- `panw.panos.threat_id`: `"36882"` — the fixed threat-signature ID assigned to all scan probes
- `panw.panos.severity`: `"high"` — baseline THREAT records use mixed severities; scan records are always `high`
- `source.ip`: fixed address from `198.51.100.0/24` (RFC 5737 TEST-NET-2, distinct from baseline `203.0.113.0/24`)
- `destination.port`: sweeping sequential values `1–65534` — baseline traffic targets port `443` only
- `panw.panos.source_zone`: `"outside"`, `panw.panos.destination_zone`: `"inside"`

**Where to see it:**
- Dashboard: `synthnet-network-overview` — threat count spike in the "Threat Events Over Time" panel; filter by `panw.panos.threat_id: "36882"`
- ES query: `GET /logs-panw.panos-default/_search?q=panw.panos.threat_id:36882&size=10`

**Scenario markers** (fields/values that confirm it's active):
- `panw.panos.threat_id: "36882"` — injected only during port_scan window
- `source.ip` matching `198.51.100.*` — RFC 5737 address, never appears in baseline traffic
- `destination.port` < 1024 in rapid sequence — baseline only sends to port 443

---

## panw.malware_detect — Malware / threat detection burst

**Schedule:** Every 3h ± up to 45 min. Duration: ~30 minutes (1800 s).

**What happens:** The probability of generating a THREAT record rises sharply during the window — roughly once per second instead of once per minute. Records use randomized threat IDs and spyware/vulnerability subtypes, simulating a malware beaconing or C2 communication event detected by the firewall.

**Data touched:**
- Data stream: `logs-panw.panos-default`
- `panw.panos.type`: `"THREAT"` — record rate increases ~60× vs. baseline
- `panw.panos.subtype`: `"spyware"` or `"vulnerability"` — same subtypes as baseline but at higher volume
- `source.ip`: `203.0.113.0/24` external net (baseline range, not a fixed attacker IP)
- `destination.ip`: production server IPs (`10.10.5.x`)
- `destination.port`: `443` (baseline destination port)
- `panw.panos.severity`: `"critical"`, `"high"`, `"medium"`, or `"low"` — drawn from the full severity range

**Where to see it:**
- Dashboard: `synthnet-network-overview` — "Threat Events Over Time" panel shows a rate spike lasting 30 min; compare baseline (~1 event/min) to active window (~1 event/s)
- ES query: `GET /logs-panw.panos-default/_search?q=panw.panos.type:THREAT&size=20`

**Scenario markers** (fields/values that confirm it's active):
- THREAT record count exceeds 50 events in a 1-minute bucket — baseline produces ~1 per minute
- `panw.panos.type: "THREAT"` with `destination.port: 443` and `destination.ip` in `10.10.5.0/24`

---

## panw.vpn_flap — VPN tunnel flap

**Schedule:** Every 3h ± up to 45 min. Duration: ~20 minutes (1200 s).

**What happens:** The site-VPN tunnel between production and DR is simulated as going down. The firewall emits SYSTEM syslog events describing tunnel state changes, and VPN-class NetFlow flows see their byte throughput collapse to approximately 1% of normal for the duration of the window. Recovery (reconnection) is logged at the end of the window.

**Data touched:**
- Data stream: `logs-panw.panos-default` (SYSTEM records) and `logs-netflow.log-default` (VPN flow bytes)
- `panw.panos.type`: `"SYSTEM"` — tunnel-state events logged as SYSTEM type
- `panw.panos.subtype`: event subtype matching VPN tunnel operations (e.g., `"vpn"`)
- `panw.panos.description`: contains tunnel state text (down/reconnecting)
- In `logs-netflow.log-default`: `network.bytes` for VPN-class flows drops to ~1% of baseline for the 20-minute window

**Where to see it:**
- Dashboard: `synthnet-network-overview` — NetFlow bytes panel shows VPN flow traffic collapse to near zero; PANW SYSTEM events visible in the log table
- ES query: `GET /logs-panw.panos-default/_search?q=panw.panos.type:SYSTEM&size=10`

**Scenario markers** (fields/values that confirm it's active):
- `panw.panos.type: "SYSTEM"` records with VPN-related subtype — SYSTEM records outside this scenario occur only once every 2 minutes (deterministic)
- `logs-netflow.log-default`: VPN flow `network.bytes` < 1% of the preceding 3h average for the same flow pair
