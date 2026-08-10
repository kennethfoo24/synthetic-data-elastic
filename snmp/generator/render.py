"""Render snmpsim .snmprec files, translate.yaml, logstash.conf, and
k8s/logstash/logstash.yaml from topology/network.yaml.

Run after updating topology:
    .venv/bin/python snmp/generator/render.py

Community-string → file mapping (snmpsim v1.x flat-file mode):
    Community "device-name" → data-dir/device-name.snmprec (filename stem).
    snmpsim-command-responder matches the incoming community string against the
    stem of each .snmprec file in --data-dir.  All 20 non-database, non-meraki
    devices are served from a single snmpsim pod on UDP 161.

snmprec variation module syntax (snmpsim built-in ``numeric``):
    Format:   OID|<type-code>:numeric|key=value,key=value,...
    The tag field is ``<SNMP-type-code>:numeric`` and the value field holds
    comma-separated key=value parameters (confirmed by snmpsim/grammar/snmprec.py
    parse + snmpsim/variation/numeric.py variate).

    Counter32 (65:numeric): ``initial=X,rate=Y,wrap=1``
        Counter increments by rate×elapsed_seconds since snmpsim boot.
        wrap=1 enables modulo wrap at Counter32 max (0xFFFFFFFF).

    TimeTicks (67:numeric): ``initial=X,rate=100``
        rate=100 ticks/s → counter reflects real wall-clock uptime progression.

    Gauge32 (66:numeric): ``initial=X,min=Y,max=Z,deviation=D,function=sin``
        value = sin(t × rate) + deviation_noise; clamped to [min, max].
        deviation (integer) adds a uniform random jitter each poll.

    Static Gauge32 (66, no module): plain ``|66|VALUE`` for fixed values.

API-key decode (Logstash Deployment):
    The elastic-credentials secret stores ELASTIC_API_KEY as base64-encoded
    "id:key" (as returned by Elasticsearch Create API Key).  The Logstash
    elasticsearch output api_key param requires the decoded "id:key" form.
    The Deployment entrypoint shell decodes it into LS_API_KEY at startup —
    no extra Secret needed.

Logstash SNMP community field:
    logstash-integration-snmp (bundled plugin) exposes the community string
    in [@metadata][host_community].  The filter copies it to device.name.
"""
from __future__ import annotations

import textwrap
from pathlib import Path
from typing import Any

import yaml

from synthgen.common.topology import Device, load_topology

PROJECT_ROOT = Path(__file__).parents[2]
TOPOLOGY_PATH = PROJECT_ROOT / "topology" / "network.yaml"
DATA_DIR = PROJECT_ROOT / "snmp" / "data"
K8S_LOGSTASH_DIR = PROJECT_ROOT / "k8s" / "logstash"

# ---------------------------------------------------------------------------
# Vendor metadata
# ---------------------------------------------------------------------------

# sysDescr template per vendor_os ({model} is substituted at render time)
_SYSDESCR: dict[str, str] = {
    "ios": (
        "Cisco IOS Software, Version 15.9(3)M, RELEASE SOFTWARE (fc2) "
        "Technical Support: http://www.cisco.com/techsupport {model}"
    ),
    "asa": (
        "Cisco Adaptive Security Appliance Software Version 9.18(2) "
        "Device Manager Version 7.18(1) {model}"
    ),
    "panos": "Palo Alto Networks PA-Series firewall {model}, PAN-OS 11.1.2",
    "arubaos": "ArubaOS (MODEL: {model}), Version 8.11.1.0",
    "os10": "Dell Networking OS10 Enterprise, Version 10.5.6.0, Build 52 {model}",
    "ilo": "HPE ProLiant {model} iLO 5 2.81 Mar 07 2024",
    "idrac": "Dell PowerEdge {model} iDRAC9 6.10.30.00",
    "alletra": "HPE Alletra {model} OS 4.4.0",
    "powerstore": "Dell EMC PowerStore {model} 3.6.0.75",
}

# sysObjectID per vendor_os (IANA/enterprise OIDs)
_SYSOID: dict[str, str] = {
    "ios": "1.3.6.1.4.1.9.1.1",
    "asa": "1.3.6.1.4.1.9.1.745",
    "panos": "1.3.6.1.4.1.25461.2.1.1",
    "arubaos": "1.3.6.1.4.1.14823.1.1.1",
    "os10": "1.3.6.1.4.1.674.11000",
    "ilo": "1.3.6.1.4.1.11.2.36.1",
    "idrac": "1.3.6.1.4.1.674.10892.5",
    "alletra": "1.3.6.1.4.1.11.2.51.1",
    "powerstore": "1.3.6.1.4.1.674.11000.2000",
}

# Number of logical interfaces by device role
_IFACE_COUNT: dict[str, int] = {
    "router": 6,
    "switch": 8,
    "firewall": 4,
    "server": 2,
    "storage": 2,
    "ap": 2,
}

# Interface name prefix by vendor_os
_IFACE_PREFIX: dict[str, str] = {
    "ios": "GigabitEthernet0/",
    "asa": "GigabitEthernet0/",
    "panos": "ethernet1/",
    "arubaos": "GE0/",
    "os10": "ethernet1/1/",
    "ilo": "eth",
    "idrac": "eth",
    "alletra": "eth",
    "powerstore": "eth",
}

# ifInOctets rate (bytes/second) by role — passed to the numeric variation module.
# snmpsim multiplies rate × elapsed_seconds; Logstash polls every 60 s.
_IFACE_RATE: dict[str, int] = {
    "router": 12_500_000,   # 100 Mbps → 12.5 MB/s
    "switch": 12_500_000,   # 100 Mbps → 12.5 MB/s
    "firewall": 6_250_000,  # 50 Mbps → 6.25 MB/s
    "server": 1_250_000,    # 10 Mbps → 1.25 MB/s
    "storage": 1_250_000,   # 10 Mbps → 1.25 MB/s
    "ap": 312_500,          # 2.5 Mbps → 312.5 KB/s
}

_COUNTER32_MOD = 2**32  # Counter32 initial-value modulus


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _hex_str(s: str) -> str:
    """Encode ASCII string to hex bytes for snmprec OCTET STRING (tag 4) fields."""
    return s.encode("ascii").hex()


def _snmp_devices(topology_path: Path = TOPOLOGY_PATH) -> list[Device]:
    """Return all non-database, non-meraki devices from topology (SNMP targets)."""
    topo = load_topology(topology_path)
    return [d for d in topo.devices if d.role != "database" and d.vendor != "meraki"]


# ---------------------------------------------------------------------------
# .snmprec renderer
# ---------------------------------------------------------------------------

def render_snmprec(device: Device) -> str:
    """Render a complete .snmprec file for one device.

    OIDs are emitted in ascending numerical order (required by snmpsim).

    Variation module syntax (snmpsim/variation/numeric.py):
        OID|<type>:numeric|initial=X,rate=Y,...
    Counter32 uses rate=bytes/s + wrap=1 for realistic traffic simulation.
    Gauge32 uses function=sin + deviation for oscillating CPU/memory/storage.
    TimeTicks uses rate=100 (ticks/s) for monotonic uptime.
    Static values (hrStorageSize) use plain |66|VALUE with no module.
    """
    lines: list[str] = []
    vo = device.vendor_os
    model = device.model

    # ── System group (1.3.6.1.2.1.1) ─────────────────────────────────────────
    sysdescr_tmpl = _SYSDESCR.get(vo, "{vendor} {model}")
    sysdescr = sysdescr_tmpl.format(model=model, vendor=device.vendor)
    lines.append(f"1.3.6.1.2.1.1.1.0|4|{_hex_str(sysdescr)}")

    sysoid = _SYSOID.get(vo, "1.3.6.1.4.1.99999.1")
    lines.append(f"1.3.6.1.2.1.1.2.0|6|{sysoid}")

    # sysUpTime: TimeTicks (67), rate=100 ticks/s → tracks real elapsed time
    lines.append("1.3.6.1.2.1.1.3.0|67:numeric|initial=8640000,rate=100")

    # sysName MUST equal the topology device name (MCP node identity)
    lines.append(f"1.3.6.1.2.1.1.5.0|4|{_hex_str(device.name)}")

    # sysLocation == site name
    lines.append(f"1.3.6.1.2.1.1.6.0|4|{_hex_str(device.site)}")

    # ── Interface table (1.3.6.1.2.1.2.2.1) ──────────────────────────────────
    n = _IFACE_COUNT.get(device.role, 2)
    prefix = _IFACE_PREFIX.get(vo, "eth")
    rate = _IFACE_RATE.get(device.role, 1_250_000)

    # ifTable column 1: ifIndex
    for i in range(1, n + 1):
        lines.append(f"1.3.6.1.2.1.2.2.1.1.{i}|2|{i}")

    # ifTable column 2: ifDescr
    for i in range(1, n + 1):
        iname = f"{prefix}{i}"
        lines.append(f"1.3.6.1.2.1.2.2.1.2.{i}|4|{_hex_str(iname)}")

    # ifTable column 8: ifOperStatus (1 = up)
    for i in range(1, n + 1):
        lines.append(f"1.3.6.1.2.1.2.2.1.8.{i}|2|1")

    # ifTable column 10: ifInOctets — Counter32:numeric
    # initial staggers per interface (simulates different start offsets).
    # Mod _COUNTER32_MOD ensures initial stays within valid Counter32 range.
    for i in range(1, n + 1):
        initial = ((i - 1) * rate * 60) % _COUNTER32_MOD
        lines.append(
            f"1.3.6.1.2.1.2.2.1.10.{i}|65:numeric|initial={initial},rate={rate},wrap=1"
        )

    # ifTable column 16: ifOutOctets — Counter32:numeric (½ of in-rate)
    out_rate = rate // 2
    for i in range(1, n + 1):
        initial = ((i - 1) * out_rate * 60) % _COUNTER32_MOD
        lines.append(
            f"1.3.6.1.2.1.2.2.1.16.{i}|65:numeric|initial={initial},rate={out_rate},wrap=1"
        )

    # ── HOST-RESOURCES-MIB (1.3.6.1.2.1.25) ──────────────────────────────────
    # hrStorageSize (RAM in KB): static 16 GiB — no variation module needed.
    lines.append("1.3.6.1.2.1.25.2.3.1.5.1|66|16777216")
    # hrStorageUsed (RAM in KB): sinusoidal oscillation ≈ 25–90% of 16 GiB
    lines.append(
        "1.3.6.1.2.1.25.2.3.1.6.1|66:numeric"
        "|initial=8388608,min=4194304,max=15728640,deviation=524288,function=sin"
    )
    # hrProcessorLoad (%): sinusoidal oscillation 5–85%, deviation ±10
    lines.append(
        "1.3.6.1.2.1.25.3.3.1.2.1|66:numeric"
        "|initial=45,min=5,max=85,deviation=10,function=sin"
    )

    # ── Storage capacity (private enterprise OID, only for storage role) ──────
    if device.role == "storage":
        # Capacity utilisation (%): sinusoidal oscillation 10–95%
        lines.append(
            "1.3.6.1.4.1.99999.1.1.0|66:numeric"
            "|initial=62,min=10,max=95,deviation=5,function=sin"
        )

    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# translate.yaml renderer
# ---------------------------------------------------------------------------

def render_translate_yaml(devices: list[Device]) -> str:
    """Render translate.yaml: device-name → {vendor, role, site, ip}."""
    table: dict[str, Any] = {}
    for d in sorted(devices, key=lambda x: x.name):
        table[d.name] = {"ip": d.ip, "role": d.role, "site": d.site, "vendor": d.vendor}
    return yaml.dump({"devices": table}, default_flow_style=False, sort_keys=True)


# ---------------------------------------------------------------------------
# logstash.conf renderer
# ---------------------------------------------------------------------------

def _translate_dict_lines(devices: list[Device]) -> str:
    """Render the inline Logstash translate dictionary block (8-space indent)."""
    rows = []
    for d in sorted(devices, key=lambda x: x.name):
        v = f"{d.vendor}|{d.role}|{d.site}"
        rows.append(f'        "{d.name}" => "{v}"')
    return "\n".join(rows)


def _host_lines(devices: list[Device]) -> str:
    """Render ``hosts => [...]`` lines for the given device list."""
    entries = []
    for d in sorted(devices, key=lambda x: x.name):
        entries.append(
            f'    {{ host => "udp:snmpsim/161" community => "{d.name}" version => "2c" }}'
        )
    return "    hosts => [\n" + ",\n".join(entries) + "\n    ]"


def render_logstash_conf(devices: list[Device]) -> str:
    """Render the Logstash pipeline config for all SNMP devices.

    Two separate snmp input blocks are used so the storage-capacity OID
    (1.3.6.1.4.1.99999.1.1.0) is only polled for the devices that actually
    have it in their .snmprec — non-storage hosts would otherwise return
    noSuchObject on every poll if the OID were in the shared get list.

    target => "snmp" nests all OID-valued fields under [snmp] to prevent
    10-level dotted OID names from polluting the top-level event namespace.

    [@metadata][host_community] is populated by logstash-integration-snmp
    (bundled with Logstash 8+/9.x) with the community string used for the
    poll.  Since community == device name, it is copied directly to device.name.

    The translate filter uses source/target (current API, not deprecated
    field/destination) to enrich vendor, role, and site from the topology.
    """
    non_storage = [d for d in devices if d.role != "storage"]
    storage = [d for d in devices if d.role == "storage"]

    common_get = """\
    get => [
      "1.3.6.1.2.1.1.1.0",          # sysDescr
      "1.3.6.1.2.1.1.2.0",          # sysObjectID
      "1.3.6.1.2.1.1.3.0",          # sysUpTime
      "1.3.6.1.2.1.1.5.0",          # sysName
      "1.3.6.1.2.1.1.6.0",          # sysLocation
      "1.3.6.1.2.1.25.2.3.1.5.1",  # hrStorageSize
      "1.3.6.1.2.1.25.2.3.1.6.1",  # hrStorageUsed
      "1.3.6.1.2.1.25.3.3.1.2.1"   # hrProcessorLoad
    ]"""

    storage_get = """\
    get => [
      "1.3.6.1.2.1.1.1.0",          # sysDescr
      "1.3.6.1.2.1.1.2.0",          # sysObjectID
      "1.3.6.1.2.1.1.3.0",          # sysUpTime
      "1.3.6.1.2.1.1.5.0",          # sysName
      "1.3.6.1.2.1.1.6.0",          # sysLocation
      "1.3.6.1.2.1.25.2.3.1.5.1",  # hrStorageSize
      "1.3.6.1.2.1.25.2.3.1.6.1",  # hrStorageUsed
      "1.3.6.1.2.1.25.3.3.1.2.1",  # hrProcessorLoad
      "1.3.6.1.4.1.99999.1.1.0"    # storage capacity % (storage devices only)
    ]"""

    walk_block = '    walk => ["1.3.6.1.2.1.2.2"]  # ifTable'
    translate_block = _translate_dict_lines(devices)

    # Build storage input block only if there are storage devices
    storage_block = ""
    if storage:
        storage_hosts = _host_lines(storage)
        storage_block = f"""
  # Storage devices — includes capacity OID absent from non-storage profiles.
  snmp {{
{storage_hosts}
{storage_get}
{walk_block}
    interval => 60
    target => "snmp"
  }}"""

    non_storage_hosts = _host_lines(non_storage)

    return f"""\
# Auto-generated by snmp/generator/render.py — re-run after updating topology.
# Community string = device name; snmpsim selects <device-name>.snmprec per request.
input {{
  # Non-storage devices
  snmp {{
{non_storage_hosts}
{common_get}
{walk_block}
    interval => 60
    target => "snmp"
  }}{storage_block}
}}

filter {{
  # [@metadata][host_community] is set by logstash-integration-snmp with the
  # community string used for this poll.  Community == device name, so copy it.
  mutate {{
    copy => {{ "[@metadata][host_community]" => "device.name" }}
  }}

  # Enrich vendor/role/site via inline translate dictionary (rendered from topology).
  # Uses source/target (current API; field/destination are deprecated).
  translate {{
    source => "device.name"
    target => "_device_meta"
    dictionary => {{
{translate_block}
    }}
    fallback => "unknown|unknown|unknown"
  }}

  # Split "vendor|role|site" into separate fields.
  mutate {{
    split => {{ "_device_meta" => "|" }}
  }}
  mutate {{
    add_field => {{
      "device.vendor" => "%{{[_device_meta][0]}}"
      "device.role"   => "%{{[_device_meta][1]}}"
      "device.site"   => "%{{[_device_meta][2]}}"
    }}
    remove_field => ["_device_meta"]
  }}
}}

output {{
  elasticsearch {{
    # LS_ES_URL and LS_API_KEY are exported by the Deployment entrypoint shell.
    # LS_API_KEY = base64-decoded ELASTIC_API_KEY (decoded "id:key" form required
    # by the Logstash elasticsearch output api_key parameter).
    hosts    => ["${{LS_ES_URL}}"]
    api_key  => "${{LS_API_KEY}}"
    data_stream           => true
    data_stream_type      => "metrics"
    data_stream_dataset   => "snmp.device"
    data_stream_namespace => "default"
  }}
}}
"""


# ---------------------------------------------------------------------------
# k8s/logstash/logstash.yaml renderer
# ---------------------------------------------------------------------------

def render_k8s_logstash_yaml(devices: list[Device]) -> str:
    """Render the Kubernetes ConfigMap + Deployment for Logstash SNMP pipeline."""
    conf = render_logstash_conf(devices)
    # Indent each line of logstash.conf by 4 spaces for the YAML literal block
    indented_conf = textwrap.indent(conf, "    ")

    return f"""\
# Auto-generated by snmp/generator/render.py — re-run after updating topology.
---
apiVersion: v1
kind: ConfigMap
metadata:
  name: logstash-snmp-config
  namespace: synthetic-network
data:
  logstash.conf: |
{indented_conf}
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: logstash
  namespace: synthetic-network
spec:
  replicas: 1
  selector:
    matchLabels: {{app: logstash}}
  template:
    metadata:
      labels: {{app: logstash}}
    spec:
      containers:
        - name: logstash
          image: docker.elastic.co/logstash/logstash:9.1.3
          # Entrypoint override: base64-decode ELASTIC_API_KEY into LS_API_KEY
          # (decoded "id:key" form) before starting Logstash.  The secret stores
          # the key base64-encoded; the elasticsearch output requires it decoded.
          command: ["/bin/sh", "-c"]
          args:
            - |
              export LS_API_KEY=$(printf '%s' "$ELASTIC_API_KEY" | base64 -d)
              export LS_ES_URL="$ES_URL"
              exec /usr/local/bin/docker-entrypoint
          env:
            - name: ELASTIC_API_KEY
              valueFrom:
                secretKeyRef:
                  name: elastic-credentials
                  key: ELASTIC_API_KEY
            - name: ES_URL
              valueFrom:
                secretKeyRef:
                  name: elastic-credentials
                  key: ES_URL
          volumeMounts:
            - name: pipeline
              mountPath: /usr/share/logstash/pipeline
          resources:
            requests: {{cpu: 200m, memory: 512Mi}}
            limits: {{memory: 1Gi}}
      volumes:
        - name: pipeline
          configMap:
            name: logstash-snmp-config
"""


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main() -> None:
    devices = _snmp_devices()
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    K8S_LOGSTASH_DIR.mkdir(parents=True, exist_ok=True)

    for d in sorted(devices, key=lambda x: x.name):
        path = DATA_DIR / f"{d.name}.snmprec"
        path.write_text(render_snmprec(d))
        print(f"  wrote {path.relative_to(PROJECT_ROOT)}")

    translate_path = DATA_DIR / "translate.yaml"
    translate_path.write_text(render_translate_yaml(devices))
    print(f"  wrote {translate_path.relative_to(PROJECT_ROOT)}")

    logstash_conf_path = DATA_DIR / "logstash.conf"
    logstash_conf_path.write_text(render_logstash_conf(devices))
    print(f"  wrote {logstash_conf_path.relative_to(PROJECT_ROOT)}")

    k8s_path = K8S_LOGSTASH_DIR / "logstash.yaml"
    k8s_path.write_text(render_k8s_logstash_yaml(devices))
    print(f"  wrote {k8s_path.relative_to(PROJECT_ROOT)}")

    print(f"\nRendered {len(devices)} SNMP device profiles.")


if __name__ == "__main__":
    main()
