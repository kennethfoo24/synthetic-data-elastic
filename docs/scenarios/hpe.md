# HPE Infrastructure Scenarios

Data stream: `metrics-snmp.device-default`
Source devices (via SNMP / Logstash snmp plugin):
- `hpe-sw-01` — Aruba-6300M switch, vendor_os `arubaos`, `10.10.2.10`
- `hpe-srv-01`, `hpe-srv-02` — DL380-Gen11 servers, vendor_os `ilo`, `10.10.5.11/12`
- `hpe-srv-dr-01` — DL380-Gen11 server (DR), vendor_os `ilo`, `10.20.5.11`
- `hpe-storage-01` — Alletra-6030 storage array, vendor_os `alletra`, `10.10.6.11`

The HPE scenarios are defined in `src/synthgen/common/scenarios.py` and fire on schedule (every 3h ± up to 45 min). Scenario timing governs which SNMP poll intervals are annotated as anomalous. The Logstash SNMP poller writes one doc per device per 5-minute poll into `metrics-snmp.device-default`. During backfill, docs contain `@timestamp` and `device.name`; in live mode the Logstash snmp plugin adds OID-mapped metrics fields.

---

## hpe.fan_failure — Cooling fan failure

**Schedule:** Every 3h ± up to 45 min. Duration: ~30 minutes (1800 s).

**What happens:** One or more fans in an HPE ProLiant server (hpe-srv-01 or hpe-srv-02) are simulated as failed or degraded. In live SNMP mode, the Logstash snmp plugin polls the HPE iLO MIB and the fan status OID (`cpqHeFltTolFanCondition`) reflects a degraded or failed state. This scenario is active for 30 minutes, after which the fan status returns to normal.

**Data touched:**
- Data stream: `metrics-snmp.device-default`
- `device.name`: `"hpe-srv-01"` or `"hpe-srv-02"` — the server reporting the fan failure
- `@timestamp`: the scenario window is 1800 s; docs with `device.name` matching an HPE server within the active window correspond to the failure period
- In live SNMP mode: `snmp.cpqHeFltTolFanCondition` transitions from `2` (ok) to `3` (degraded) or `4` (failed) during the window

**Where to see it:**
- Dashboard: `synthnet-hpe-infrastructure` — fan health panel; look for status changes on `hpe-srv-01` or `hpe-srv-02` during the 30-minute window
- ES query: `GET /metrics-snmp.device-default/_search?q=device.name:hpe-srv-01&sort=@timestamp:desc&size=10`

**Scenario markers** (fields/values that confirm it's active):
- `device.name: "hpe-srv-01"` or `"hpe-srv-02"` in docs with `@timestamp` falling in a 30-minute active window (check `src/synthgen/common/scenarios.py` `active_window("hpe.fan_failure", t, seed)`)
- In live SNMP mode: `snmp.cpqHeFltTolFanCondition` ≠ `2` on an HPE server device

---

## hpe.port_saturation — Switch port bandwidth saturation

**Schedule:** Every 3h ± up to 45 min. Duration: ~25 minutes (1500 s).

**What happens:** An uplink port on the HPE Aruba-6300M switch (`hpe-sw-01`) is simulated at or near 100% utilization. In live SNMP mode, the `ifInOctets` / `ifOutOctets` counters (RFC 2233 IF-MIB OIDs `1.3.6.1.2.1.2.2.1.10` / `1.3.6.1.2.1.2.2.1.16`) for the saturated port interface increment at a rate near the port's rated bandwidth. This scenario lasts 25 minutes and affects the switch's interface utilization metrics.

**Data touched:**
- Data stream: `metrics-snmp.device-default`
- `device.name`: `"hpe-sw-01"` — the Aruba switch reporting the saturated port
- `@timestamp`: docs for `hpe-sw-01` within the 1500-second active window correspond to the saturation period
- In live SNMP mode: `snmp.ifInOctets` or `snmp.ifOutOctets` for the affected interface index near the port rate limit; `snmp.ifOperStatus` = `1` (up)

**Where to see it:**
- Dashboard: `synthnet-hpe-infrastructure` — port utilization panel for `hpe-sw-01`; look for sustained high bandwidth on one interface during the 25-minute window
- ES query: `GET /metrics-snmp.device-default/_search?q=device.name:hpe-sw-01&sort=@timestamp:desc&size=10`

**Scenario markers** (fields/values that confirm it's active):
- `device.name: "hpe-sw-01"` in docs with `@timestamp` in the active window
- In live SNMP mode: per-interface byte counter delta exceeding the nominal baseline rate by a significant margin for a sustained period

---

## hpe.raid_degraded — RAID array degraded

**Schedule:** Every 3h ± up to 45 min. Duration: ~30 minutes (1800 s).

**What happens:** A disk in the HPE Alletra-6030 storage array (`hpe-storage-01`) is simulated as failed, placing the RAID set in a degraded state. In live SNMP mode, the HPE storage MIB field `cpqDaLogDrvStatus` transitions from `2` (ok) to `3` (degraded) for the 30-minute window. The scenario also affects `hpe-srv-01` and `hpe-srv-02` if they mount volumes from this array.

**Data touched:**
- Data stream: `metrics-snmp.device-default`
- `device.name`: `"hpe-storage-01"` — the storage array reporting the degraded RAID
- `@timestamp`: docs for `hpe-storage-01` within the 1800-second active window correspond to the degraded period
- In live SNMP mode: `snmp.cpqDaLogDrvStatus` = `3` (degraded) instead of the baseline `2` (ok) on `hpe-storage-01`

**Where to see it:**
- Dashboard: `synthnet-hpe-infrastructure` — storage health panel; `cpqDaLogDrvStatus` ≠ ok on `hpe-storage-01` during the 30-minute window is the pattern
- ES query: `GET /metrics-snmp.device-default/_search?q=device.name:hpe-storage-01&sort=@timestamp:desc&size=10`

**Scenario markers** (fields/values that confirm it's active):
- `device.name: "hpe-storage-01"` in docs with `@timestamp` falling in the 30-minute active window
- In live SNMP mode: `snmp.cpqDaLogDrvStatus` = `3` on `hpe-storage-01` — baseline value is `2` (ok)
