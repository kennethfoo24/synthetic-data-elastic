# Task 5 Report — SNMP telemetry via snmpsim + Logstash pipeline

**Status:** DONE  
**Commit:** `f81ed9b`  
**Tests:** 286 passed, 2 skipped — ruff clean — `kubectl kustomize k8s/ >/dev/null` clean

---

## What was built

### 1. `snmp/generator/render.py`
Reads `topology/network.yaml`, filters to 20 non-database, non-meraki devices, and renders:
- `snmp/data/<device>.snmprec` — one snmpsim data file per device
- `snmp/data/translate.yaml` — device → {vendor, role, site, ip}
- `snmp/data/logstash.conf` — Logstash pipeline (reference copy)
- `k8s/logstash/logstash.yaml` — ConfigMap (with embedded logstash.conf) + Deployment

Re-run with `.venv/bin/python snmp/generator/render.py` after any topology change.

### 2. `snmp/data/` (20 committed .snmprec files)
Each file contains OIDs in ascending order as required by snmpsim:
- **System group**: sysDescr (vendor-appropriate string), sysObjectID (enterprise OID), sysUpTime (TimeTicks, `numeric` variation), **sysName == device name** (MCP node identity), sysLocation == site
- **ifTable** (2–8 ports by role: router=6, switch=8, firewall=4, server/storage=2): ifIndex, ifDescr, ifOperStatus=1, ifInOctets + ifOutOctets as Counter32 with `numeric` variation (increments per poll, simulates real traffic)
- **HOST-RESOURCES-MIB**: hrStorageSize (static), hrStorageUsed (Gauge32, wandering), hrProcessorLoad (Gauge32, wandering 5–85%)
- **Storage-only**: private OID `1.3.6.1.4.1.99999.1.1.0` (capacity % Gauge32)

**Numeric variation module syntax** (snmpsim built-in):
```
<OID>|<tag>|numeric:<initial>:<min>:<max>:<step>
```
- Counter32 (65): always increments by `<step>` per request (traffic simulation)
- Gauge32 (66): random walk in [min, max] by ±step (CPU/memory/storage oscillation)
- TimeTicks (67): always increments (uptime simulation)
- Counter32 initial values are `(rate * iface_index) % 2^32` to stay within range

### 3. `k8s/generators/snmpsim.yaml`
- Deployment: `kennethfoo24/synthetic-netgen:latest` image (SHA-pinned by deploy.sh), command override → `snmpsim-command-responder --data-dir=/app/snmp/data --agent-udpv4-endpoint=0.0.0.0:161`
- Service: `snmpsim` UDP 161 (ClusterIP)
- **Community → file mapping**: snmpsim v1.x flat-file mode: community `cisco-rtr-core-01` → `/app/snmp/data/cisco-rtr-core-01.snmprec`

### 4. `k8s/logstash/logstash.yaml`
- **ConfigMap `logstash-snmp-config`**: embeds rendered `logstash.conf` (20 host entries, `get` + `walk` OIDs, filter with translate, ES output)
- **Deployment `logstash`**: `docker.elastic.co/logstash/logstash:9.1.3` (already pinned, no sed substitution needed)
  - `[snmp_community]` field set by `logstash-integration-snmp` (bundled); copied to `device.name`
  - Inline translate dictionary maps device name → `vendor|role|site`; split into `device.vendor`, `device.role`, `device.site`
  - Data stream: `metrics-snmp.device-default`
  - Resources: 512Mi–1Gi

**API key decode approach** (entrypoint shell override — no new Secret):
```sh
export LS_API_KEY=$(printf '%s' "$ELASTIC_API_KEY" | base64 -d)
export LS_ES_URL="$ES_URL"
exec /usr/local/bin/docker-entrypoint
```
The `elastic-credentials` secret stores `ELASTIC_API_KEY` base64-encoded. The Logstash `elasticsearch` output `api_key` param requires the decoded `id:key` form. The shell fragment decodes it at container start and passes it as `${LS_API_KEY}` (Logstash env-var substitution).

### 5. `Dockerfile`
- Changed `pip install --no-cache-dir .` → `pip install --no-cache-dir ".[snmp]"`
- Added `COPY snmp/data ./snmp/data`
- `pyproject.toml` `[project.optional-dependencies]` gained `snmp = ["snmpsim>=1.1"]`

### 6. `src/synthsetup/validate.py` — `check_snmp_devices`
```
POST /metrics-snmp.device-default/_search
  query: range @timestamp ≥ now-5m
  aggs: terms on device.name.keyword size 100
Checks: total > 0 AND distinct buckets >= 18
```
Added to `CHECKS` list.

### 7. Tests
- `tests/test_snmp_render.py`: 186 parametrized + class-based unit tests
  - Device enumeration (count ≥18, no database/meraki)
  - sysName == device.name for every device
  - Counter32/Gauge32/TimeTicks all use `|numeric:` syntax
  - 4 colon-separated fields in every numeric variation entry
  - OIDs in ascending order (snmpsim requirement)
  - Storage-only OID present iff role==storage
  - Interface count matches role
  - translate.yaml completeness + field correctness
  - logstash.conf has all 20 hosts, correct data stream config
- `tests/test_validate.py`: 5 new SNMP check tests (respx mocked)

### 8. `deploy.sh` additions
```sh
sed "s|synthetic-netgen:latest|synthetic-netgen:$IMAGE_TAG|" k8s/generators/snmpsim.yaml | kubectl apply -f -
kubectl apply -f k8s/logstash/logstash.yaml
kubectl -n synthetic-network rollout status deploy/snmpsim --timeout=120s
kubectl -n synthetic-network rollout status deploy/logstash --timeout=300s
```

### 9. `k8s/kustomization.yaml`
Added `generators/snmpsim.yaml` and `logstash/logstash.yaml`.

---

## Device count note
The topology has 20 non-database, non-meraki devices (the brief said 18; the difference is `meraki-mx-01` also excluded as vendor=meraki). Validate check threshold remains ≥18 distinct, which 20 devices satisfies.

## Concerns / known limitations
1. **data_stream_type=metrics ILM**: no explicit ILM policy or rollover alias created. Elasticsearch's built-in metrics data stream template handles this; no issue expected in Elastic 8+/9.x.
2. **Counter32 wrap**: at 12.5 MB/s for routers, ifInOctets wraps roughly every 344 seconds. This is standard SNMP counter behavior; downstream metric calculations use delta computation.

---

## Phase 2 Fix Report — coordinator review remediation

**Commit:** `1dad9b4`
**Tests:** 352 passed, 2 skipped — ruff clean — `kubectl kustomize k8s/ >/dev/null` clean

### Errors fixed

#### 1. CRITICAL — snmprec variation module syntax
Phase 1 used positional `|65|numeric:<init>:<min>:<max>:<step>` — format does not exist in snmpsim. Verified via `snmpsim.grammar.snmprec.SnmprecGrammar().parse()` and source inspection of `snmpsim/variation/numeric.py`.

Correct syntax: tag field = `<type-code>:numeric`, value field = `key=value` CSV:
```
1.3.6.1.2.1.1.3.0|67:numeric|initial=8640000,rate=100
1.3.6.1.2.1.2.2.1.10.1|65:numeric|initial=0,rate=12500000,wrap=1
1.3.6.1.2.1.25.2.3.1.5.1|66|16777216          # static — no module
1.3.6.1.2.1.25.2.3.1.6.1|66:numeric|initial=8388608,min=4194304,max=15728640,deviation=524288,function=sin
1.3.6.1.2.1.25.3.3.1.2.1|66:numeric|initial=45,min=5,max=85,deviation=10,function=sin
1.3.6.1.4.1.99999.1.1.0|66:numeric|initial=62,min=10,max=95,deviation=5,function=sin
```
`rate` is bytes/second (snmpsim multiplies by elapsed seconds). hrStorageSize is static (plain `|66|16777216`). All 20 `.snmprec` files regenerated.

#### 2. CRITICAL — Logstash community field
`[snmp_community]` does not exist. logstash-integration-snmp exposes the community string at `[@metadata][host_community]`. Fixed:
```
mutate { copy => { "[@metadata][host_community]" => "device.name" } }
```

#### 3. HIGH — validate.py aggregation field
Changed `"field": "device.name.keyword"` → `"field": "device.name"`. Under the built-in metrics ECS template, string fields map directly to keyword with no `.keyword` sub-field.

#### 4. MEDIUM — translate filter deprecated params
Changed `field` → `source` and `destination` → `target` in the translate filter.

#### 5. MEDIUM — storage OID polling scope
Split single snmp input block into two: non-storage (16 devices, no capacity OID) and storage (4 devices, includes `1.3.6.1.4.1.99999.1.1.0`). Prevents noSuchObject errors every 60 s for 16 hosts.

#### 6. MEDIUM — OID field explosion
Added `target => "snmp"` to both snmp input blocks. OID-valued fields are now nested under `[snmp]` instead of polluting the top-level event namespace.

#### 7. Tests — syntax assertions corrected + parser-truth test added
- All `|65|numeric:`, `|66|numeric:`, `|67|numeric:` assertions → `|65:numeric|`, `|66:numeric|`, `|67:numeric|`
- Removed "4 colon-separated fields" assertion (inapplicable to key=value format)
- Added `test_numeric_syntax_is_key_value`: validates every `:numeric|` line has `key=value` pairs
- Added `test_counter32_has_wrap`: validates `wrap=1` present on all Counter32 variation lines
- Added `test_storage_size_is_static`: validates hrStorageSize uses `|66|` not `|66:numeric|`
- Added `TestSnmprecGrammarParse.test_all_lines_parse`: feeds every line of every committed `.snmprec` through `snmpsim.grammar.snmprec.SnmprecGrammar().parse()` — invalid syntax now blocked by CI
- Added `TestSnmprecGrammarParse.test_committed_files_match_render`: byte-identity check — committed files must match fresh `render.py` output
- Added `test_community_field_uses_metadata`, `test_target_snmp_prevents_field_explosion`, `test_two_input_blocks`, corrected `test_translate_uses_source_target`

#### 8. pyproject.toml
Added `"snmpsim>=1.1"` to `dev` extras so grammar parser tests run in CI.
