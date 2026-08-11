# Dell Infrastructure Scenarios

Data stream: `metrics-snmp.device-default`
Source devices (via SNMP / Logstash snmp plugin):
- `dell-sw-01` — S4148F-ON switch, vendor_os `os10`, `10.10.2.11`
- `dell-sw-dr` — S4128F-ON switch (DR), vendor_os `os10`, `10.20.2.2`
- `dell-srv-01`, `dell-srv-02` — R760 servers, vendor_os `idrac`, `10.10.5.21/22`
- `dell-storage-01` — PowerStore-1200T, vendor_os `powerstore`, `10.10.6.21`
- `dell-storage-dr` — PowerStore-500T (DR), vendor_os `powerstore`, `10.20.6.21`

The Dell scenarios are defined in `src/synthgen/common/scenarios.py` and fire on schedule (every 3h ± up to 45 min). The Logstash SNMP poller writes one doc per device per 5-minute poll into `metrics-snmp.device-default`. During backfill, docs contain `@timestamp` and `device.name`; in live mode the Logstash snmp plugin adds OID-mapped metrics fields.

---

## dell.psu_failure — Power supply unit failure

**Schedule:** Every 3h ± up to 45 min. Duration: ~25 minutes (1500 s).

**What happens:** One PSU in a Dell R760 server (`dell-srv-01` or `dell-srv-02`) is simulated as failed or absent. In live SNMP mode, the Dell iDRAC MIB field `powerSupplyStatus` (OID `1.3.6.1.4.1.674.10892.5.4.600.12.1.5`) transitions from `3` (ok) to `6` (failed) for the 25-minute window. The second PSU remains ok, simulating a single-PSU failure on a dual-PSU server.

**Data touched:**
- Data stream: `metrics-snmp.device-default`
- `device.name`: `"dell-srv-01"` or `"dell-srv-02"` — the server with the failed PSU
- `@timestamp`: docs for the affected Dell server within the 1500-second active window correspond to the failure period
- In live SNMP mode: `snmp.powerSupplyStatus` = `6` (failed) on the affected server; baseline is `3` (ok)

**Where to see it:**
- Dashboard: `synthnet-dell-infrastructure` — PSU health panel; look for `powerSupplyStatus` ≠ ok on a Dell server device during the 25-minute window
- ES query: `GET /metrics-snmp.device-default/_search?q=device.name:dell-srv-01&sort=@timestamp:desc&size=10`

**Scenario markers** (fields/values that confirm it's active):
- `device.name: "dell-srv-01"` or `"dell-srv-02"` in docs with `@timestamp` in the active window
- In live SNMP mode: `snmp.powerSupplyStatus` = `6` on a Dell server — baseline is `3` (ok) for all PSUs

---

## dell.mem_leak — Memory leak (rising memory utilization)

**Schedule:** Every 3h ± up to 45 min. Duration: ~60 minutes (3600 s).

**What happens:** A Dell R760 server is simulated with a gradual memory leak: free memory decreases steadily over the 60-minute window, simulating a process that is not releasing allocated memory. In live SNMP mode, the standard HOST-RESOURCES-MIB `hrStorageUsed` OID (`.1.3.6.1.2.1.25.2.3.1.6`) for the physical memory storage row increases monotonically from the start of the window to a high utilization level by the end.

**Data touched:**
- Data stream: `metrics-snmp.device-default`
- `device.name`: `"dell-srv-01"` or `"dell-srv-02"` — the server exhibiting the memory leak
- `@timestamp`: the 60-minute window (3600 s) is the longest Dell scenario; docs for the device in this range show rising memory usage
- In live SNMP mode: `snmp.hrStorageUsed` (for memory storage type) increases monotonically over the window; `snmp.hrStorageSize` (total installed RAM) remains constant — ratio indicates utilization climbing toward capacity

**Where to see it:**
- Dashboard: `synthnet-dell-infrastructure` — memory utilization panel; `hrStorageUsed` / `hrStorageSize` ratio increases continuously over the 60-minute window
- ES query: `GET /metrics-snmp.device-default/_search?q=device.name:dell-srv-02&sort=@timestamp:desc&size=12`

**Scenario markers** (fields/values that confirm it's active):
- `device.name: "dell-srv-01"` or `"dell-srv-02"` across docs spanning the 60-minute window with monotonically increasing memory utilization
- In live SNMP mode: `snmp.hrStorageUsed` increases in each successive 5-minute poll sample — baseline shows stable or slowly fluctuating memory use

---

## dell.capacity_breach — Storage capacity threshold breach

**Schedule:** Every 3h ± up to 45 min. Duration: ~60 minutes (3600 s).

**What happens:** A Dell PowerStore storage array (`dell-storage-01` or `dell-storage-dr`) is simulated at or above its configured capacity threshold. In live SNMP mode, the PowerStore MIB or HOST-RESOURCES-MIB `hrStorageUsed` for the storage volume exceeds the threshold (typically ≥ 85% of `hrStorageSize`). This scenario runs for 60 minutes, the longest duration of any Dell scenario.

**Data touched:**
- Data stream: `metrics-snmp.device-default`
- `device.name`: `"dell-storage-01"` or `"dell-storage-dr"` — the storage array breaching capacity
- `@timestamp`: docs for the affected Dell storage device within the 3600-second active window correspond to the breach period
- In live SNMP mode: `snmp.hrStorageUsed` / `snmp.hrStorageSize` ≥ 0.85 on the storage device — baseline is typically < 0.70; `snmp.hrStorageType` identifies the volume type

**Where to see it:**
- Dashboard: `synthnet-dell-infrastructure` — storage capacity panel; utilization ratio for `dell-storage-01` or `dell-storage-dr` crosses the 85% threshold line for the 60-minute window
- ES query: `GET /metrics-snmp.device-default/_search?q=device.name:dell-storage-01&sort=@timestamp:desc&size=12`

**Scenario markers** (fields/values that confirm it's active):
- `device.name: "dell-storage-01"` or `"dell-storage-dr"` in docs with `@timestamp` falling in the 60-minute active window
- In live SNMP mode: `snmp.hrStorageUsed` / `snmp.hrStorageSize` ratio ≥ 0.85 on a Dell storage device — baseline ratio is < 0.70
