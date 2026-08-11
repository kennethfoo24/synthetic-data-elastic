# Cisco ASA Scenarios

Data stream: `logs-cisco_asa.log-default`
Source device: `cisco-asa-dr` (model ASA5545-X, `10.20.0.1`, DR site)

---

## asa.brute_force — AAA brute-force authentication attack

**Schedule:** Every 3h ± up to 45 min. Duration: ~5 minutes (300 s).

**What happens:** A fixed attacker IP from `198.51.100.0/24` sends a burst of failed AAA authentication attempts against the ASA, targeting service accounts `svc1`–`svc5`. Message volume peaks at mid-window (tent function) — up to 15 extra failed-auth messages per second at peak — then tapers back to zero, simulating a credential-stuffing burst.

**Data touched:**
- Data stream: `logs-cisco_asa.log-default`
- `cisco.asa.message_id`: `"113005"` — `AAA user authentication Rejected`; baseline also emits 113005 but from randomized `203.0.113.x` IPs
- `source.ip`: fixed address from `198.51.100.0/24` (RFC 5737 TEST-NET-2) — baseline uses `203.0.113.0/24`
- `cisco.asa.aaa.user`: `"svc1"` through `"svc5"` — narrow account set vs. baseline's `user1`–`user40`
- `log.level`: `"informational"` (ASA severity 6)

**Where to see it:**
- Dashboard: `synthnet-network-overview` — spike in `%ASA-6-113005` message count; filter by `cisco.asa.message_id: "113005"` and `source.ip: 198.51.100.*`
- ES query: `GET /logs-cisco_asa.log-default/_search?q=cisco.asa.message_id:113005+AND+source.ip:198.51.100.*&size=10`

**Scenario markers** (fields/values that confirm it's active):
- `source.ip` matching `198.51.100.*` in message_id 113005 records — this CIDR never appears in baseline 113005 traffic
- `cisco.asa.aaa.user` in `["svc1", "svc2", "svc3", "svc4", "svc5"]` — baseline uses `user{1..40}`

---

## asa.conn_storm — Connection storm (TCP flood)

**Schedule:** Every 3h ± up to 45 min. Duration: ~8 minutes (450 s).

**What happens:** A fixed storm IP from `198.51.100.51`–`198.51.100.200` opens and tears down a rapidly increasing number of TCP connections to inside targets. The connection rate builds linearly over the window (up to 25 extra connections per second by the end). The ASA logs a mix of 302013 (built), 302014 (teardown), and 106023 (deny) messages sourced from the storm IP.

**Data touched:**
- Data stream: `logs-cisco_asa.log-default`
- `cisco.asa.message_id`: `"302013"`, `"302014"`, `"106023"` — same message IDs as baseline but from a fixed source IP at higher rate
- `source.ip`: fixed address from `198.51.100.51`–`198.51.100.200` (RFC 5737 TEST-NET-2)
- `destination.ip`: production/DR server IPs (`10.10.5.x`, `10.20.5.x`)
- `cisco.asa.connection_id`: sequential connection IDs from the storm source
- `log.level`: `"informational"` (severity 6) for 302013/302014; `"warning"` (severity 4) for 106023

**Where to see it:**
- Dashboard: `synthnet-network-overview` — connection rate chart; 302013 build count spikes linearly over the 8-minute window
- ES query: `GET /logs-cisco_asa.log-default/_search?q=source.ip:198.51.100.*+AND+cisco.asa.message_id:302013&size=10`

**Scenario markers** (fields/values that confirm it's active):
- `source.ip` matching `198.51.100.*` combined with `cisco.asa.message_id: "302013"` — fixed storm IP never appears in baseline
- Event rate for 302013 + 302014 from a single source IP exceeds 10/s — baseline spreads across the full `203.0.113.0/24` range

---

## asa.failover — ASA HA failover event

**Schedule:** Every 3h ± up to 45 min. Duration: ~25 minutes (1500 s).

**What happens:** The standby ASA unit becomes ACTIVE for approximately 22 minutes (90% of the window), generating `%ASA-1-104001` alerts. At the tail of the window (final 10%), the primary unit regains ACTIVE status and `%ASA-1-104002` is emitted, simulating a failover and recovery cycle.

**Data touched:**
- Data stream: `logs-cisco_asa.log-default`
- `cisco.asa.message_id`: `"104001"` — `(Secondary) Switching to ACTIVE - Loss of communication with mate on interface failover-link`; emitted for 90% of the window
- `cisco.asa.message_id`: `"104002"` — `(Primary) Switching to STANDBY - Other side is ACTIVE`; emitted in the final 10%
- `log.level`: `"alert"` (ASA severity 1) — the only alert-severity message emitted by this source; all baseline traffic is severity 4 or 6

**Where to see it:**
- Dashboard: `synthnet-network-overview` — ASA alert-severity events visible in the log table; filter `log.level: alert`
- ES query: `GET /logs-cisco_asa.log-default/_search?q=cisco.asa.message_id:104001&size=10`

**Scenario markers** (fields/values that confirm it's active):
- `cisco.asa.message_id: "104001"` or `"104002"` — these message IDs never appear in baseline traffic
- `log.level: "alert"` (severity 1) — baseline ASA messages are severity 4 or 6 only
