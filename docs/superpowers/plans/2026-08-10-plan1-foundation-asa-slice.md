# Plan 1: Foundation + Cisco ASA Vertical Slice — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stand up the repo, CI, shared topology model, and pattern engine, then prove the whole architecture end-to-end with one source: synthetic Cisco ASA syslog flowing through a Fleet-managed Elastic Agent on Kubernetes into an Elastic Serverless project, populating the pre-built Cisco ASA dashboard.

**Architecture:** Python package `synthgen` (generators + shared libs) and `synthsetup` (Fleet/Kibana/ES automation), built into one Docker image pushed to Docker Hub by GitHub Actions. Kubernetes runs: a run-once `fleet-setup` Job (creates agent policy + `cisco_asa` integration via Fleet API, writes enrollment secret), a Fleet-enrolled Elastic Agent Deployment listening on UDP 9001, and a `syslog-gen` Deployment emitting wire-format ASA messages at pattern-engine-driven rates. A `validate` script proves data is landing.

**Tech Stack:** Python 3.12, pydantic v2, httpx (+respx for test mocks), PyYAML, kubernetes (Python client), pytest, ruff. Docker multi-arch via GitHub Actions. Plain K8s manifests + kustomize.

**Plan series:** This is Plan 1 of 4. Plan 2 = remaining sources (IOS/PANW/NetFlow/SNMP/DBs/Meraki). Plan 3 = backfill + custom dashboards + 24 scenarios. Plan 4 = MCP app. Spec: `docs/superpowers/specs/2026-08-10-synthetic-network-observability-design.md`.

## Global Constraints

- GitHub repo: `github.com/kennethfoo24/synthetic-data-elastic`; Docker Hub namespace: `kennethfoo24`; generator image name: `kennethfoo24/synthetic-netgen`.
- K8s namespace: `synthetic-network`. Agent policy name: `synthetic-network`.
- Production site subnet `10.10.0.0/16`, DR site subnet `10.20.0.0/16`.
- ASA syslog UDP port on the Agent: `9001`.
- All randomness must flow through a seeded PRNG keyed on `(GLOBAL_SEED, stable_key, time_bucket)` — never bare `random()` — so backfill (Plan 3) can reproduce identical values. `GLOBAL_SEED = 20260810`.
- Setup scripts must be idempotent: safe to re-run against a fresh OR half-configured project.
- Secrets never committed: `.env` is gitignored; `secrets.example.yaml` and `.env.example` carry placeholders only.
- Layout note (refinement of spec): Python code uses a `src/` layout (`src/synthgen`, `src/synthsetup`). The spec's `generators/` grouping maps to subpackages of `synthgen`; `setup/` maps to `synthsetup`. `topology/`, `k8s/`, `docs/` stay as in spec.
- Deviation from spec (approved fix): the spec's inter-site backup flows target "DR storage" but the DR device list had no storage device. `network.yaml` adds `dell-storage-dr` (10.20.6.21), making 27 devices total.

---

### Task 1: Project scaffolding

**Files:**
- Create: `pyproject.toml`, `.gitignore`, `.env.example`, `README.md`
- Create: `src/synthgen/__init__.py`, `src/synthsetup/__init__.py`, `tests/__init__.py`

**Interfaces:**
- Produces: installable package `synthgen`/`synthsetup`; `pytest` and `ruff check` runnable from repo root. Constant `synthgen.GLOBAL_SEED = 20260810`.

- [ ] **Step 1: Write `pyproject.toml`**

```toml
[build-system]
requires = ["setuptools>=69"]
build-backend = "setuptools.build_meta"

[project]
name = "synthetic-data-elastic"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
    "pydantic>=2.7",
    "PyYAML>=6.0",
    "httpx>=0.27",
    "kubernetes>=29.0",
]

[project.optional-dependencies]
dev = ["pytest>=8.0", "respx>=0.21", "ruff>=0.5"]

[tool.setuptools.packages.find]
where = ["src"]

[tool.pytest.ini_options]
testpaths = ["tests"]

[tool.ruff]
line-length = 100
src = ["src", "tests"]
```

- [ ] **Step 2: Write `.gitignore`**

```
.env
__pycache__/
*.egg-info/
.pytest_cache/
.ruff_cache/
dist/
.venv/
```

- [ ] **Step 3: Write `.env.example`**

```bash
# Elastic Serverless Observability project endpoints + API key.
# Copy to .env and fill in. .env is gitignored.
ES_URL=https://<project>.es.<region>.elastic.cloud
KIBANA_URL=https://<project>.kb.<region>.elastic.cloud
ELASTIC_API_KEY=<base64 api key>
```

- [ ] **Step 4: Write package inits**

`src/synthgen/__init__.py`:
```python
GLOBAL_SEED = 20260810
```
`src/synthsetup/__init__.py` and `tests/__init__.py`: empty files.

- [ ] **Step 5: Write `README.md`** (short: what this is, link to spec, `make up` teaser — 10 lines is fine)

- [ ] **Step 6: Verify toolchain**

Run: `python3.12 -m venv .venv && .venv/bin/pip install -q -e '.[dev]' && .venv/bin/pytest; .venv/bin/ruff check .`
Expected: pytest exits 5 ("no tests ran" is OK at this point), ruff passes.

- [ ] **Step 7: Commit**

```bash
git add -A && git commit -m "chore: project scaffolding (src layout, pytest, ruff)"
```

---

### Task 2: Topology model — `network.yaml` + validated loader

**Files:**
- Create: `topology/network.yaml`
- Create: `src/synthgen/common/__init__.py`, `src/synthgen/common/topology.py`
- Test: `tests/test_topology.py`

**Interfaces:**
- Produces:
  - `synthgen.common.topology.load_topology(path: str | Path) -> Topology`
  - `Topology.devices: list[Device]`, `Topology.flows: list[Flow]`, `Topology.device(name: str) -> Device` (KeyError if missing), `Topology.devices_by_vendor_os(vendor_os: str) -> list[Device]`
  - `Device` fields: `name: str, vendor: str, vendor_os: str, model: str, role: str, site: str ("production"|"dr"), ip: str`
  - `Flow` fields: `name: str, src: str, dst: str, dst_port: int, proto: str ("tcp"|"udp"), flow_class: str ("user"|"replication"|"vpn"|"backup"|"app"), baseline_bps: int`

- [ ] **Step 1: Write the failing tests**

`tests/test_topology.py`:
```python
import ipaddress
from synthgen.common.topology import load_topology

TOPO = load_topology("topology/network.yaml")

def test_device_count_and_sites():
    assert len(TOPO.devices) == 27
    assert {d.site for d in TOPO.devices} == {"production", "dr"}

def test_ips_unique_and_in_site_subnet():
    ips = [d.ip for d in TOPO.devices]
    assert len(ips) == len(set(ips))
    for d in TOPO.devices:
        net = "10.10.0.0/16" if d.site == "production" else "10.20.0.0/16"
        assert ipaddress.ip_address(d.ip) in ipaddress.ip_network(net), d.name

def test_flow_endpoints_exist():
    names = {d.name for d in TOPO.devices}
    for f in TOPO.flows:
        assert f.src in names, f.name
        assert f.dst in names, f.name

def test_inter_site_flows_present():
    classes = set()
    for f in TOPO.flows:
        if TOPO.device(f.src).site != TOPO.device(f.dst).site:
            classes.add(f.flow_class)
    assert {"vpn", "replication", "backup"} <= classes

def test_lookup_helpers():
    assert TOPO.device("cisco-asa-dr").vendor_os == "asa"
    assert len(TOPO.devices_by_vendor_os("asa")) == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_topology.py -v` — Expected: FAIL (ModuleNotFoundError).

- [ ] **Step 3: Write `topology/network.yaml`**

```yaml
# Single source of truth for the synthetic network.
# Every generator, backfill, and validation derives from this file.
sites:
  production: {subnet: 10.10.0.0/16}
  dr: {subnet: 10.20.0.0/16}

devices:
  # ── Production ──────────────────────────────────────────────
  - {name: palo-fw-prod,       vendor: paloalto, vendor_os: panos,   model: PA-3260,        role: firewall, site: production, ip: 10.10.0.1}
  - {name: cisco-rtr-core-01,  vendor: cisco,    vendor_os: ios,     model: ISR4451,        role: router,   site: production, ip: 10.10.1.1}
  - {name: cisco-rtr-core-02,  vendor: cisco,    vendor_os: ios,     model: ISR4451,        role: router,   site: production, ip: 10.10.1.2}
  - {name: cisco-sw-access-01, vendor: cisco,    vendor_os: ios,     model: C9300-48T,      role: switch,   site: production, ip: 10.10.2.1}
  - {name: cisco-sw-access-02, vendor: cisco,    vendor_os: ios,     model: C9300-48T,      role: switch,   site: production, ip: 10.10.2.2}
  - {name: cisco-sw-access-03, vendor: cisco,    vendor_os: ios,     model: C9300-48T,      role: switch,   site: production, ip: 10.10.2.3}
  - {name: hpe-sw-01,          vendor: hpe,      vendor_os: arubaos, model: Aruba-6300M,    role: switch,   site: production, ip: 10.10.2.10}
  - {name: dell-sw-01,         vendor: dell,     vendor_os: os10,    model: S4148F-ON,      role: switch,   site: production, ip: 10.10.2.11}
  - {name: meraki-mx-01,       vendor: meraki,   vendor_os: meraki,  model: MX250,          role: firewall, site: production, ip: 10.10.3.1}
  - {name: meraki-ap-01,       vendor: meraki,   vendor_os: meraki,  model: MR46,           role: ap,       site: production, ip: 10.10.3.11}
  - {name: meraki-ap-02,       vendor: meraki,   vendor_os: meraki,  model: MR46,           role: ap,       site: production, ip: 10.10.3.12}
  - {name: hpe-srv-01,         vendor: hpe,      vendor_os: ilo,     model: DL380-Gen11,    role: server,   site: production, ip: 10.10.5.11}
  - {name: hpe-srv-02,         vendor: hpe,      vendor_os: ilo,     model: DL380-Gen11,    role: server,   site: production, ip: 10.10.5.12}
  - {name: dell-srv-01,        vendor: dell,     vendor_os: idrac,   model: R760,           role: server,   site: production, ip: 10.10.5.21}
  - {name: dell-srv-02,        vendor: dell,     vendor_os: idrac,   model: R760,           role: server,   site: production, ip: 10.10.5.22}
  - {name: hpe-storage-01,     vendor: hpe,      vendor_os: alletra, model: Alletra-6030,   role: storage,  site: production, ip: 10.10.6.11}
  - {name: dell-storage-01,    vendor: dell,     vendor_os: powerstore, model: PowerStore-1200T, role: storage, site: production, ip: 10.10.6.21}
  - {name: mongodb-prod,       vendor: mongodb,  vendor_os: mongod,  model: replica-primary, role: database, site: production, ip: 10.10.7.11}
  - {name: postgres-prod,      vendor: postgres, vendor_os: postgres, model: primary,       role: database, site: production, ip: 10.10.7.21}
  # ── DR ──────────────────────────────────────────────────────
  - {name: cisco-asa-dr,       vendor: cisco,    vendor_os: asa,     model: ASA5545-X,      role: firewall, site: dr, ip: 10.20.0.1}
  - {name: cisco-rtr-dr,       vendor: cisco,    vendor_os: ios,     model: ISR4331,        role: router,   site: dr, ip: 10.20.1.1}
  - {name: cisco-sw-dr-01,     vendor: cisco,    vendor_os: ios,     model: C9300-24T,      role: switch,   site: dr, ip: 10.20.2.1}
  - {name: dell-sw-dr,         vendor: dell,     vendor_os: os10,    model: S4128F-ON,      role: switch,   site: dr, ip: 10.20.2.2}
  - {name: hpe-srv-dr-01,      vendor: hpe,      vendor_os: ilo,     model: DL380-Gen11,    role: server,   site: dr, ip: 10.20.5.11}
  - {name: dell-storage-dr,    vendor: dell,     vendor_os: powerstore, model: PowerStore-500T, role: storage, site: dr, ip: 10.20.6.21}
  - {name: mongodb-dr,         vendor: mongodb,  vendor_os: mongod,  model: replica-secondary, role: database, site: dr, ip: 10.20.7.11}
  - {name: postgres-dr,        vendor: postgres, vendor_os: postgres, model: standby,       role: database, site: dr, ip: 10.20.7.21}

flows:
  # user/app traffic inside production
  - {name: wifi-to-web,        src: meraki-ap-01,  dst: hpe-srv-01,      dst_port: 443,   proto: tcp, flow_class: user,        baseline_bps: 4000000}
  - {name: wifi2-to-web,       src: meraki-ap-02,  dst: hpe-srv-02,      dst_port: 443,   proto: tcp, flow_class: user,        baseline_bps: 3000000}
  - {name: web-to-postgres,    src: hpe-srv-01,    dst: postgres-prod,   dst_port: 5432,  proto: tcp, flow_class: app,         baseline_bps: 1500000}
  - {name: web2-to-postgres,   src: hpe-srv-02,    dst: postgres-prod,   dst_port: 5432,  proto: tcp, flow_class: app,         baseline_bps: 1000000}
  - {name: app-to-mongo,       src: dell-srv-01,   dst: mongodb-prod,    dst_port: 27017, proto: tcp, flow_class: app,         baseline_bps: 2000000}
  - {name: app2-to-mongo,      src: dell-srv-02,   dst: mongodb-prod,    dst_port: 27017, proto: tcp, flow_class: app,         baseline_bps: 1200000}
  - {name: srv-to-hpe-storage, src: hpe-srv-01,    dst: hpe-storage-01,  dst_port: 3260,  proto: tcp, flow_class: app,         baseline_bps: 5000000}
  - {name: srv-to-dell-storage, src: dell-srv-01,  dst: dell-storage-01, dst_port: 3260,  proto: tcp, flow_class: app,         baseline_bps: 5000000}
  # inter-site
  - {name: site-vpn,           src: palo-fw-prod,  dst: cisco-asa-dr,    dst_port: 4500,  proto: udp, flow_class: vpn,         baseline_bps: 800000}
  - {name: mongo-replication,  src: mongodb-prod,  dst: mongodb-dr,      dst_port: 27017, proto: tcp, flow_class: replication, baseline_bps: 600000}
  - {name: pg-replication,     src: postgres-prod, dst: postgres-dr,     dst_port: 5432,  proto: tcp, flow_class: replication, baseline_bps: 500000}
  - {name: nightly-backup-hpe, src: hpe-storage-01, dst: dell-storage-dr, dst_port: 2049, proto: tcp, flow_class: backup,      baseline_bps: 20000000}
  - {name: nightly-backup-dell, src: dell-storage-01, dst: dell-storage-dr, dst_port: 2049, proto: tcp, flow_class: backup,    baseline_bps: 20000000}
  # dr-local
  - {name: dr-web-to-pg,       src: hpe-srv-dr-01, dst: postgres-dr,     dst_port: 5432,  proto: tcp, flow_class: app,         baseline_bps: 200000}
```

- [ ] **Step 4: Write `src/synthgen/common/topology.py`** (+ empty `src/synthgen/common/__init__.py`)

```python
from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel


class Device(BaseModel):
    name: str
    vendor: str
    vendor_os: str
    model: str
    role: str
    site: Literal["production", "dr"]
    ip: str


class Flow(BaseModel):
    name: str
    src: str
    dst: str
    dst_port: int
    proto: Literal["tcp", "udp"]
    flow_class: Literal["user", "app", "replication", "vpn", "backup"]
    baseline_bps: int


class Topology(BaseModel):
    devices: list[Device]
    flows: list[Flow]

    def device(self, name: str) -> Device:
        for d in self.devices:
            if d.name == name:
                return d
        raise KeyError(name)

    def devices_by_vendor_os(self, vendor_os: str) -> list[Device]:
        return [d for d in self.devices if d.vendor_os == vendor_os]


def load_topology(path: str | Path) -> Topology:
    raw = yaml.safe_load(Path(path).read_text())
    topo = Topology(devices=raw["devices"], flows=raw["flows"])
    names = {d.name for d in topo.devices}
    for f in topo.flows:
        if f.src not in names or f.dst not in names:
            raise ValueError(f"flow {f.name} references unknown device")
    return topo
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_topology.py -v` — Expected: 5 PASS.

- [ ] **Step 6: Commit**

```bash
git add -A && git commit -m "feat: topology model with 27-device prod+dr network and flow matrix"
```

---

### Task 3: Pattern engine (diurnal / weekly / jitter, deterministic)

**Files:**
- Create: `src/synthgen/common/patterns.py`
- Test: `tests/test_patterns.py`

**Interfaces:**
- Produces:
  - `synthgen.common.patterns.rate_multiplier(t: datetime, flow_class: str, key: str, seed: int = GLOBAL_SEED) -> float` — combined diurnal×weekly×jitter multiplier, deterministic for identical args. `t` must be timezone-aware UTC.
  - `synthgen.common.patterns.in_backup_window(t: datetime) -> bool` — True 01:00–03:00 UTC.
  - Later plans (backfill, NetFlow, SNMP) call these same functions — do not add module-level mutable state.

- [ ] **Step 1: Write the failing tests**

`tests/test_patterns.py`:
```python
from datetime import datetime, timezone
from synthgen.common.patterns import rate_multiplier, in_backup_window

MON_PEAK = datetime(2026, 8, 10, 12, 0, tzinfo=timezone.utc)   # Monday noon
MON_NIGHT = datetime(2026, 8, 10, 2, 30, tzinfo=timezone.utc)  # Monday 02:30
SAT_PEAK = datetime(2026, 8, 8, 12, 0, tzinfo=timezone.utc)    # Saturday noon

def test_deterministic():
    a = rate_multiplier(MON_PEAK, "user", "flow-x")
    b = rate_multiplier(MON_PEAK, "user", "flow-x")
    assert a == b

def test_different_keys_differ():
    assert rate_multiplier(MON_PEAK, "user", "flow-x") != rate_multiplier(MON_PEAK, "user", "flow-y")

def test_diurnal_peak_above_trough():
    assert rate_multiplier(MON_PEAK, "user", "k") > 2 * rate_multiplier(MON_NIGHT, "user", "k")

def test_weekend_dip_user_only():
    assert rate_multiplier(SAT_PEAK, "user", "k") < 0.5 * rate_multiplier(MON_PEAK, "user", "k")
    assert rate_multiplier(SAT_PEAK, "replication", "k") > 0.7 * rate_multiplier(MON_PEAK, "replication", "k")

def test_backup_window():
    assert in_backup_window(MON_NIGHT)
    assert not in_backup_window(MON_PEAK)

def test_multiplier_bounds():
    for hour in range(24):
        t = MON_PEAK.replace(hour=hour)
        m = rate_multiplier(t, "user", "k")
        assert 0.0 < m < 2.0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_patterns.py -v` — Expected: FAIL (ModuleNotFoundError).

- [ ] **Step 3: Write `src/synthgen/common/patterns.py`**

```python
from __future__ import annotations

import random
from datetime import datetime

from synthgen import GLOBAL_SEED

# Hourly diurnal anchor points (UTC), linearly interpolated between.
_DIURNAL = {0: 0.25, 2: 0.20, 5: 0.25, 7: 0.50, 10: 1.00, 16: 1.00, 19: 0.60, 23: 0.30}
_ANCHORS = sorted(_DIURNAL)


def _diurnal(t: datetime) -> float:
    h = t.hour + t.minute / 60.0
    pts = _ANCHORS + [_ANCHORS[0] + 24]
    for lo, hi in zip(pts, pts[1:]):
        if lo <= h < hi:
            v_lo, v_hi = _DIURNAL[lo % 24], _DIURNAL[hi % 24]
            return v_lo + (v_hi - v_lo) * (h - lo) / (hi - lo)
    return _DIURNAL[_ANCHORS[-1]]


def _weekly(t: datetime, flow_class: str) -> float:
    if flow_class == "user" and t.weekday() >= 5:
        return 0.30
    return 1.0


def _jitter(t: datetime, key: str, seed: int) -> float:
    minute_bucket = int(t.timestamp()) // 60
    rng = random.Random((seed, key, minute_bucket))
    return rng.uniform(0.85, 1.15)


def rate_multiplier(t: datetime, flow_class: str, key: str, seed: int = GLOBAL_SEED) -> float:
    if t.tzinfo is None:
        raise ValueError("t must be timezone-aware")
    return _diurnal(t) * _weekly(t, flow_class) * _jitter(t, key, seed)


def in_backup_window(t: datetime) -> bool:
    return 1 <= t.hour < 3
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_patterns.py -v` — Expected: 6 PASS.

- [ ] **Step 5: Commit**

```bash
git add -A && git commit -m "feat: deterministic diurnal/weekly/jitter pattern engine"
```

---

### Task 4: Cisco ASA wire formats

**Files:**
- Create: `src/synthgen/syslog_gen/__init__.py`, `src/synthgen/syslog_gen/formats/__init__.py`, `src/synthgen/syslog_gen/formats/asa.py`
- Test: `tests/test_asa_formats.py`

**Interfaces:**
- Produces (all return a complete syslog line, str, no trailing newline; `ts` is aware-UTC datetime; hostname comes from the Device):
  - `asa_302013(ts, hostname, conn_id, src_ip, src_port, dst_ip, dst_port) -> str` (Built inbound TCP)
  - `asa_302014(ts, hostname, conn_id, src_ip, src_port, dst_ip, dst_port, duration, byte_count) -> str` (Teardown TCP)
  - `asa_106023(ts, hostname, src_ip, src_port, dst_ip, dst_port, acl="OUTSIDE_IN") -> str` (Deny tcp)
  - `asa_113005(ts, hostname, user, user_ip, server="10.20.7.5") -> str` (AAA auth rejected)
  - `asa_timestamp(ts) -> str` (e.g. `Aug 10 2026 12:34:56`)
- Consumes: nothing from other tasks.

- [ ] **Step 1: Write the failing tests**

`tests/test_asa_formats.py`:
```python
import re
from datetime import datetime, timezone
from synthgen.syslog_gen.formats import asa

TS = datetime(2026, 8, 10, 12, 34, 56, tzinfo=timezone.utc)

def test_timestamp_format():
    assert asa.asa_timestamp(TS) == "Aug 10 2026 12:34:56"

def test_302013_built_connection():
    m = asa.asa_302013(TS, "cisco-asa-dr", 12345, "198.51.100.10", 54321, "10.20.5.11", 443)
    assert m == (
        "<166>Aug 10 2026 12:34:56 cisco-asa-dr : %ASA-6-302013: "
        "Built inbound TCP connection 12345 for outside:198.51.100.10/54321 "
        "(198.51.100.10/54321) to inside:10.20.5.11/443 (10.20.5.11/443)"
    )

def test_302014_teardown():
    m = asa.asa_302014(TS, "cisco-asa-dr", 12345, "198.51.100.10", 54321, "10.20.5.11", 443,
                       duration="0:01:02", byte_count=8412)
    assert "%ASA-6-302014: Teardown TCP connection 12345" in m
    assert "duration 0:01:02 bytes 8412" in m
    assert m.startswith("<166>")

def test_106023_deny():
    m = asa.asa_106023(TS, "cisco-asa-dr", "203.0.113.7", 41000, "10.20.5.11", 22)
    assert m.startswith("<164>")  # severity 4
    assert '%ASA-4-106023: Deny tcp src outside:203.0.113.7/41000 dst inside:10.20.5.11/22' in m
    assert 'by access-group "OUTSIDE_IN"' in m

def test_113005_auth_rejected():
    m = asa.asa_113005(TS, "cisco-asa-dr", "jsmith", "203.0.113.7")
    assert "%ASA-6-113005: AAA user authentication Rejected" in m
    assert "user = jsmith" in m and "user IP = 203.0.113.7" in m

def test_priority_encoding():
    # local4 facility (20): PRI = 20*8 + severity
    assert re.match(r"^<166>", asa.asa_302013(TS, "h", 1, "1.1.1.1", 1, "2.2.2.2", 2))
    assert re.match(r"^<164>", asa.asa_106023(TS, "h", "1.1.1.1", 1, "2.2.2.2", 2))
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_asa_formats.py -v` — Expected: FAIL.

- [ ] **Step 3: Write `src/synthgen/syslog_gen/formats/asa.py`** (+ empty `__init__.py` files)

```python
from __future__ import annotations

from datetime import datetime

_FACILITY = 20  # local4, ASA default


def asa_timestamp(ts: datetime) -> str:
    return ts.strftime("%b %-d %Y %H:%M:%S")


def _line(ts: datetime, hostname: str, severity: int, msg_id: str, body: str) -> str:
    pri = _FACILITY * 8 + severity
    return f"<{pri}>{asa_timestamp(ts)} {hostname} : %ASA-{severity}-{msg_id}: {body}"


def asa_302013(ts, hostname, conn_id, src_ip, src_port, dst_ip, dst_port) -> str:
    body = (
        f"Built inbound TCP connection {conn_id} "
        f"for outside:{src_ip}/{src_port} ({src_ip}/{src_port}) "
        f"to inside:{dst_ip}/{dst_port} ({dst_ip}/{dst_port})"
    )
    return _line(ts, hostname, 6, "302013", body)


def asa_302014(ts, hostname, conn_id, src_ip, src_port, dst_ip, dst_port, duration, byte_count) -> str:
    body = (
        f"Teardown TCP connection {conn_id} "
        f"for outside:{src_ip}/{src_port} to inside:{dst_ip}/{dst_port} "
        f"duration {duration} bytes {byte_count} TCP FINs"
    )
    return _line(ts, hostname, 6, "302014", body)


def asa_106023(ts, hostname, src_ip, src_port, dst_ip, dst_port, acl: str = "OUTSIDE_IN") -> str:
    body = (
        f"Deny tcp src outside:{src_ip}/{src_port} dst inside:{dst_ip}/{dst_port} "
        f'by access-group "{acl}" [0x0, 0x0]'
    )
    return _line(ts, hostname, 4, "106023", body)


def asa_113005(ts, hostname, user, user_ip, server: str = "10.20.7.5") -> str:
    body = (
        "AAA user authentication Rejected : reason = AAA failure : "
        f"server = {server} : user = {user} : user IP = {user_ip}"
    )
    return _line(ts, hostname, 6, "113005", body)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_asa_formats.py -v` — Expected: 6 PASS.

Note: `%-d` (no zero-pad day) is glibc/macOS strftime; both Linux containers and macOS support it.

- [ ] **Step 5: Commit**

```bash
git add -A && git commit -m "feat: Cisco ASA syslog wire formats (302013/302014/106023/113005)"
```

---

### Task 5: UDP emitter + ASA generator loop + CLI entrypoint

**Files:**
- Create: `src/synthgen/syslog_gen/emitter.py`, `src/synthgen/syslog_gen/asa_source.py`, `src/synthgen/__main__.py`
- Test: `tests/test_emitter.py`, `tests/test_asa_source.py`

**Interfaces:**
- Consumes: `load_topology`, `rate_multiplier` (Tasks 2–3), `formats.asa` (Task 4).
- Produces:
  - `emitter.UdpSender(host: str, port: int)` with `.send(line: str) -> None` (appends `\n`, sends UTF-8 datagram).
  - `asa_source.generate_batch(topo: Topology, t: datetime, seed: int = GLOBAL_SEED) -> list[str]` — messages for one 1-second tick for every `vendor_os == "asa"` device. PURE (no I/O, no sleep) so Plan 3's backfill can reuse it verbatim for historical ticks.
  - CLI: `python -m synthgen syslog-asa --target-host H --target-port P --topology PATH [--seed N]` — loops forever: every second, `generate_batch(now)` → send each.

- [ ] **Step 1: Write the failing tests**

`tests/test_emitter.py`:
```python
import socket
from synthgen.syslog_gen.emitter import UdpSender

def test_udp_sender_delivers_datagram():
    rx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    rx.bind(("127.0.0.1", 0))
    rx.settimeout(2)
    port = rx.getsockname()[1]
    UdpSender("127.0.0.1", port).send("hello syslog")
    data, _ = rx.recvfrom(4096)
    assert data == b"hello syslog\n"
    rx.close()
```

`tests/test_asa_source.py`:
```python
from datetime import datetime, timezone
from synthgen.common.topology import load_topology
from synthgen.syslog_gen.asa_source import generate_batch

TOPO = load_topology("topology/network.yaml")
PEAK = datetime(2026, 8, 10, 12, 0, 0, tzinfo=timezone.utc)
NIGHT = datetime(2026, 8, 10, 2, 30, 0, tzinfo=timezone.utc)

def test_batch_is_deterministic():
    assert generate_batch(TOPO, PEAK) == generate_batch(TOPO, PEAK)

def test_batch_contains_valid_asa_lines():
    batch = generate_batch(TOPO, PEAK)
    assert len(batch) >= 1
    assert all("%ASA-" in line and "cisco-asa-dr" in line for line in batch)

def test_peak_busier_than_night():
    # Average over 60 ticks to smooth jitter.
    peak = sum(len(generate_batch(TOPO, PEAK.replace(second=s))) for s in range(60))
    night = sum(len(generate_batch(TOPO, NIGHT.replace(second=s))) for s in range(60))
    assert peak > night

def test_mix_includes_denies():
    lines = [l for s in range(60) for l in generate_batch(TOPO, PEAK.replace(second=s))]
    assert any("106023" in l for l in lines)
    assert any("302013" in l for l in lines)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_emitter.py tests/test_asa_source.py -v` — Expected: FAIL.

- [ ] **Step 3: Write `src/synthgen/syslog_gen/emitter.py`**

```python
from __future__ import annotations

import socket


class UdpSender:
    def __init__(self, host: str, port: int):
        self._addr = (host, port)
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    def send(self, line: str) -> None:
        self._sock.sendto((line + "\n").encode("utf-8"), self._addr)
```

- [ ] **Step 4: Write `src/synthgen/syslog_gen/asa_source.py`**

```python
from __future__ import annotations

import random
from datetime import datetime

from synthgen import GLOBAL_SEED
from synthgen.common.patterns import rate_multiplier
from synthgen.common.topology import Topology
from synthgen.syslog_gen.formats import asa

# Peak-hour message rate per ASA device, scaled by the pattern engine.
PEAK_MSGS_PER_SEC = 8
EXTERNAL_NET = "203.0.113."  # TEST-NET-3 for synthetic "internet" clients


def generate_batch(topo: Topology, t: datetime, seed: int = GLOBAL_SEED) -> list[str]:
    lines: list[str] = []
    for dev in topo.devices_by_vendor_os("asa"):
        mult = rate_multiplier(t, "user", f"asa:{dev.name}", seed)
        rng = random.Random((seed, dev.name, int(t.timestamp())))
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
                dur = f"0:{rng.randint(0, 9)}:{rng.randint(10, 59)}"
                lines.append(asa.asa_302014(t, dev.name, conn_id, src_ip, src_port, dst.ip, 443,
                                            duration=dur, byte_count=rng.randint(500, 2_000_000)))
            elif roll < 0.97:
                lines.append(asa.asa_106023(t, dev.name, src_ip, src_port, dst.ip,
                                            rng.choice([22, 23, 3389, 445])))
            else:
                lines.append(asa.asa_113005(t, dev.name, f"user{rng.randint(1, 40)}", src_ip))
    return lines
```

- [ ] **Step 5: Write `src/synthgen/__main__.py`**

```python
from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime, timezone

from synthgen import GLOBAL_SEED
from synthgen.common.topology import load_topology
from synthgen.syslog_gen.asa_source import generate_batch
from synthgen.syslog_gen.emitter import UdpSender


def main() -> None:
    parser = argparse.ArgumentParser(prog="synthgen")
    sub = parser.add_subparsers(dest="mode", required=True)
    asa_p = sub.add_parser("syslog-asa")
    asa_p.add_argument("--target-host", required=True)
    asa_p.add_argument("--target-port", type=int, required=True)
    asa_p.add_argument("--topology", default="topology/network.yaml")
    asa_p.add_argument("--seed", type=int, default=GLOBAL_SEED)
    args = parser.parse_args()

    topo = load_topology(args.topology)
    sender = UdpSender(args.target_host, args.target_port)
    print(f"synthgen {args.mode}: -> {args.target_host}:{args.target_port}", flush=True)
    sent = 0
    while True:
        tick = datetime.now(timezone.utc)
        for line in generate_batch(topo, tick, args.seed):
            try:
                sender.send(line)
                sent += 1
            except OSError as exc:
                print(f"send failed ({exc}); retrying next tick", file=sys.stderr, flush=True)
                break
        if sent and sent % 500 < 10:
            print(f"sent={sent}", flush=True)
        time.sleep(max(0.0, 1.0 - (datetime.now(timezone.utc) - tick).total_seconds()))


if __name__ == "__main__":
    main()
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_emitter.py tests/test_asa_source.py -v` — Expected: all PASS.

- [ ] **Step 7: Smoke-run the CLI locally**

Run (background, 5s): `.venv/bin/python -m synthgen syslog-asa --target-host 127.0.0.1 --target-port 9999 & sleep 5; kill %1`
Expected: startup line printed, no tracebacks (nothing listens on 9999 — UDP doesn't care).

- [ ] **Step 8: Commit**

```bash
git add -A && git commit -m "feat: ASA syslog generator loop with UDP emitter and CLI"
```

---

### Task 6: Dockerfile, GitHub repo, CI → Docker Hub

**Files:**
- Create: `Dockerfile`, `.dockerignore`, `.github/workflows/validate.yaml`, `.github/workflows/build-push.yaml`

**Interfaces:**
- Produces: image `kennethfoo24/synthetic-netgen:{latest,<sha>}` containing the package + `topology/network.yaml` at `/app/topology/network.yaml`; entrypoint `python -m synthgen`. K8s manifests (Task 8) reference this image.

- [ ] **Step 1: Write `Dockerfile`**

```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir .
COPY topology ./topology
ENTRYPOINT ["python", "-m", "synthgen"]
```

- [ ] **Step 2: Write `.dockerignore`**

```
.venv
.git
tests
docs
k8s
.github
```

- [ ] **Step 3: Verify the image builds and runs**

Run: `docker build -t kennethfoo24/synthetic-netgen:dev . && docker run --rm kennethfoo24/synthetic-netgen:dev --help`
Expected: build succeeds; argparse usage text printed.

- [ ] **Step 4: Write `.github/workflows/validate.yaml`**

```yaml
name: validate
on:
  pull_request:
  push:
    branches: [main]
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: {python-version: "3.12"}
      - run: pip install -e '.[dev]'
      - run: ruff check .
      - run: pytest -v
  kustomize:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: azure/setup-kubectl@v4
      - run: if [ -d k8s ]; then kubectl kustomize k8s/ > /dev/null; fi
```

- [ ] **Step 5: Write `.github/workflows/build-push.yaml`**

```yaml
name: build-push
on:
  push:
    branches: [main]
jobs:
  netgen:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: docker/setup-qemu-action@v3
      - uses: docker/setup-buildx-action@v3
      - uses: docker/login-action@v3
        with:
          username: ${{ secrets.DOCKERHUB_USERNAME }}
          password: ${{ secrets.DOCKERHUB_TOKEN }}
      - uses: docker/build-push-action@v6
        with:
          context: .
          platforms: linux/amd64,linux/arm64
          push: true
          tags: |
            kennethfoo24/synthetic-netgen:latest
            kennethfoo24/synthetic-netgen:${{ github.sha }}
```

- [ ] **Step 6: Create the GitHub repo and push**

```bash
gh repo create kennethfoo24/synthetic-data-elastic --public --source=. --push
```
Then **ASK THE USER** to add repo secrets `DOCKERHUB_USERNAME` and `DOCKERHUB_TOKEN` (Docker Hub → Account Settings → Personal access tokens). This is a human step — do not proceed to Step 7 until confirmed.

- [ ] **Step 7: Verify CI**

Run: `gh run watch --exit-status` (after push). Expected: `validate` and `build-push` both green; `docker pull kennethfoo24/synthetic-netgen:latest` succeeds.

- [ ] **Step 8: Commit** (workflows were part of the push; commit any fixes made)

```bash
git add -A && git commit -m "ci: build+push synthetic-netgen to Docker Hub" || true
```

---

### Task 7: Fleet setup script (`synthsetup.fleet_setup`)

**Files:**
- Create: `src/synthsetup/fleet_client.py`, `src/synthsetup/fleet_setup.py`
- Test: `tests/test_fleet_client.py`

**Interfaces:**
- Consumes: env vars `KIBANA_URL`, `ELASTIC_API_KEY`; optional `K8S_NAMESPACE` (default `synthetic-network`).
- Produces:
  - `FleetClient(kibana_url: str, api_key: str)` with methods:
    - `get_or_create_agent_policy(name: str) -> str` (returns policy id)
    - `latest_package_version(pkg: str) -> str`
    - `ensure_package_policy(name: str, policy_id: str, package: str, version: str, inputs: dict) -> None` (create if absent by name; treat HTTP 409 as success)
    - `get_or_create_enrollment_token(policy_id: str) -> str`
    - `default_fleet_url() -> str`
  - `fleet_setup.main()` — orchestrates: policy → cisco_asa integration (UDP 0.0.0.0:9001) → enrollment token + fleet URL → K8s Secret `agent-enrollment` (keys `FLEET_URL`, `FLEET_ENROLLMENT_TOKEN`) in `K8S_NAMESPACE`, created/updated via the kubernetes client (in-cluster config).
  - Task 8's Job manifest runs `python -m synthsetup.fleet_setup`; the agent Deployment consumes the `agent-enrollment` secret.
- The `cisco_asa` inputs dict (Fleet "simplified" package-policy format):

```python
CISCO_ASA_INPUTS = {
    "cisco_asa-udp": {
        "enabled": True,
        "streams": {
            "cisco_asa.log": {
                "enabled": True,
                "vars": {"syslog_host": "0.0.0.0", "syslog_port": 9001},
            }
        },
    }
}
```

- [ ] **Step 1: Write the failing tests** (respx mocks; no live calls)

`tests/test_fleet_client.py`:
```python
import httpx
import respx
from synthsetup.fleet_client import FleetClient

KB = "https://kb.example.com"

def client() -> FleetClient:
    return FleetClient(KB, "fake-key")

@respx.mock
def test_creates_policy_when_absent():
    respx.get(f"{KB}/api/fleet/agent_policies").respond(json={"items": []})
    route = respx.post(f"{KB}/api/fleet/agent_policies").respond(
        json={"item": {"id": "pol-1", "name": "synthetic-network"}})
    assert client().get_or_create_agent_policy("synthetic-network") == "pol-1"
    body = route.calls.last.request.content
    assert b"synthetic-network" in body

@respx.mock
def test_reuses_existing_policy():
    respx.get(f"{KB}/api/fleet/agent_policies").respond(
        json={"items": [{"id": "pol-9", "name": "synthetic-network"}]})
    assert client().get_or_create_agent_policy("synthetic-network") == "pol-9"

@respx.mock
def test_package_policy_409_is_success():
    respx.get(f"{KB}/api/fleet/epm/packages/cisco_asa").respond(
        json={"item": {"version": "2.34.0"}})
    respx.post(f"{KB}/api/fleet/package_policies").respond(409, json={"message": "exists"})
    c = client()
    v = c.latest_package_version("cisco_asa")
    c.ensure_package_policy("cisco-asa-syslog", "pol-1", "cisco_asa", v, inputs={})

@respx.mock
def test_enrollment_token():
    respx.get(f"{KB}/api/fleet/enrollment_api_keys").respond(
        json={"items": [{"policy_id": "pol-1", "api_key": "tok==", "active": True}]})
    assert client().get_or_create_enrollment_token("pol-1") == "tok=="

@respx.mock
def test_auth_headers_sent():
    route = respx.get(f"{KB}/api/fleet/agent_policies").respond(json={"items": []})
    respx.post(f"{KB}/api/fleet/agent_policies").respond(json={"item": {"id": "p"}})
    client().get_or_create_agent_policy("x")
    req = route.calls.last.request
    assert req.headers["authorization"] == "ApiKey fake-key"
    assert req.headers["kbn-xsrf"] == "true"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_fleet_client.py -v` — Expected: FAIL.

- [ ] **Step 3: Write `src/synthsetup/fleet_client.py`**

```python
from __future__ import annotations

import httpx


class FleetSetupError(RuntimeError):
    pass


class FleetClient:
    def __init__(self, kibana_url: str, api_key: str):
        self.http = httpx.Client(
            base_url=kibana_url.rstrip("/"),
            headers={
                "Authorization": f"ApiKey {api_key}",
                "kbn-xsrf": "true",
                "Content-Type": "application/json",
            },
            timeout=60,
        )

    def _check(self, r: httpx.Response, what: str) -> httpx.Response:
        if r.status_code >= 400:
            raise FleetSetupError(f"{what} failed: HTTP {r.status_code}: {r.text[:500]}")
        return r

    def get_or_create_agent_policy(self, name: str) -> str:
        r = self._check(self.http.get("/api/fleet/agent_policies",
                                      params={"kuery": f'name:"{name}"'}), "list agent policies")
        for item in r.json().get("items", []):
            if item["name"] == name:
                return item["id"]
        r = self._check(self.http.post("/api/fleet/agent_policies", json={
            "name": name, "namespace": "default",
            "description": "Synthetic network observability (managed by synthsetup)",
            "monitoring_enabled": ["logs", "metrics"],
        }), "create agent policy")
        return r.json()["item"]["id"]

    def latest_package_version(self, pkg: str) -> str:
        r = self._check(self.http.get(f"/api/fleet/epm/packages/{pkg}"), f"get package {pkg}")
        return r.json()["item"]["version"]

    def ensure_package_policy(self, name: str, policy_id: str, package: str,
                              version: str, inputs: dict) -> None:
        r = self.http.post("/api/fleet/package_policies", json={
            "name": name, "policy_id": policy_id,
            "package": {"name": package, "version": version},
            "inputs": inputs,
        })
        if r.status_code == 409:
            return  # already exists — idempotent success
        self._check(r, f"create package policy {name}")

    def get_or_create_enrollment_token(self, policy_id: str) -> str:
        r = self._check(self.http.get("/api/fleet/enrollment_api_keys"), "list enrollment keys")
        for item in r.json().get("items", []):
            if item.get("policy_id") == policy_id and item.get("active"):
                return item["api_key"]
        r = self._check(self.http.post("/api/fleet/enrollment_api_keys",
                                       json={"policy_id": policy_id}), "create enrollment key")
        return r.json()["item"]["api_key"]

    def default_fleet_url(self) -> str:
        r = self._check(self.http.get("/api/fleet/fleet_server_hosts"), "list fleet server hosts")
        items = r.json().get("items", [])
        if not items:
            raise FleetSetupError("no fleet server hosts configured on this project")
        default = next((i for i in items if i.get("is_default")), items[0])
        return default["host_urls"][0]
```

- [ ] **Step 4: Write `src/synthsetup/fleet_setup.py`**

```python
from __future__ import annotations

import base64
import os

from kubernetes import client as k8s, config as k8s_config

from synthsetup.fleet_client import FleetClient

AGENT_POLICY = "synthetic-network"
ASA_PORT = 9001

CISCO_ASA_INPUTS = {
    "cisco_asa-udp": {
        "enabled": True,
        "streams": {
            "cisco_asa.log": {
                "enabled": True,
                "vars": {"syslog_host": "0.0.0.0", "syslog_port": ASA_PORT},
            }
        },
    }
}


def write_enrollment_secret(namespace: str, fleet_url: str, token: str) -> None:
    k8s_config.load_incluster_config()
    api = k8s.CoreV1Api()
    body = k8s.V1Secret(
        metadata=k8s.V1ObjectMeta(name="agent-enrollment", namespace=namespace),
        data={
            "FLEET_URL": base64.b64encode(fleet_url.encode()).decode(),
            "FLEET_ENROLLMENT_TOKEN": base64.b64encode(token.encode()).decode(),
        },
    )
    try:
        api.create_namespaced_secret(namespace, body)
    except k8s.exceptions.ApiException as exc:
        if exc.status != 409:
            raise
        api.replace_namespaced_secret("agent-enrollment", namespace, body)


def main() -> None:
    fleet = FleetClient(os.environ["KIBANA_URL"], os.environ["ELASTIC_API_KEY"])
    namespace = os.environ.get("K8S_NAMESPACE", "synthetic-network")

    policy_id = fleet.get_or_create_agent_policy(AGENT_POLICY)
    print(f"agent policy: {policy_id}", flush=True)

    version = fleet.latest_package_version("cisco_asa")
    fleet.ensure_package_policy("cisco-asa-syslog", policy_id, "cisco_asa", version,
                                CISCO_ASA_INPUTS)
    print(f"cisco_asa {version}: integration policy ensured (dashboards installed)", flush=True)

    token = fleet.get_or_create_enrollment_token(policy_id)
    fleet_url = fleet.default_fleet_url()
    write_enrollment_secret(namespace, fleet_url, token)
    print(f"enrollment secret written to {namespace}/agent-enrollment", flush=True)


if __name__ == "__main__":
    main()
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_fleet_client.py -v` — Expected: 5 PASS.

- [ ] **Step 6: Live schema check (requires `.env` with real project)**

The simplified package-policy input keys (`cisco_asa-udp`, stream `cisco_asa.log`, vars `syslog_host`/`syslog_port`) are asserted from docs, not verified. Verify against the live project:

```bash
set -a; source .env; set +a
curl -s -H "Authorization: ApiKey $ELASTIC_API_KEY" \
  "$KIBANA_URL/api/fleet/epm/packages/cisco_asa" \
  | python3 -c "import json,sys; d=json.load(sys.stdin)['item']; \
print(d['version']); \
print(json.dumps([{ 'template': pt['name'], 'inputs': [i['type'] for i in pt.get('inputs',[])]} for pt in d.get('policy_templates',[])], indent=2))"
```

Compare the input types and (via the package's `data_streams` in the same response) the stream var names against `CISCO_ASA_INPUTS`. If they differ, fix the constant and its test. **This step must not be skipped** — a wrong key here fails only at deploy time.

- [ ] **Step 7: Commit**

```bash
git add -A && git commit -m "feat: Fleet setup — agent policy, cisco_asa integration, enrollment secret"
```

---

### Task 8: Kubernetes manifests

**Files:**
- Create: `k8s/namespace.yaml`, `k8s/rbac.yaml`, `k8s/secrets.example.yaml`, `k8s/jobs/fleet-setup.yaml`, `k8s/elastic-agent.yaml`, `k8s/generators/syslog-gen.yaml`, `k8s/kustomization.yaml`

**Interfaces:**
- Consumes: image `kennethfoo24/synthetic-netgen:latest` (Task 6); secret `agent-enrollment` written by fleet-setup Job (Task 7); user-created secret `elastic-credentials` (from `deploy.sh`, Task 9) with keys `ES_URL`, `KIBANA_URL`, `ELASTIC_API_KEY`.
- Produces: Service `elastic-agent` (UDP 9001) that generators target; namespace `synthetic-network`.

- [ ] **Step 1: Write `k8s/namespace.yaml`**

```yaml
apiVersion: v1
kind: Namespace
metadata:
  name: synthetic-network
```

- [ ] **Step 2: Write `k8s/rbac.yaml`** (fleet-setup Job needs to write the enrollment secret)

```yaml
apiVersion: v1
kind: ServiceAccount
metadata:
  name: fleet-setup
  namespace: synthetic-network
---
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: fleet-setup-secrets
  namespace: synthetic-network
rules:
  - apiGroups: [""]
    resources: [secrets]
    verbs: [create, get, replace, update]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: fleet-setup-secrets
  namespace: synthetic-network
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: Role
  name: fleet-setup-secrets
subjects:
  - kind: ServiceAccount
    name: fleet-setup
    namespace: synthetic-network
```

- [ ] **Step 3: Write `k8s/secrets.example.yaml`** (documentation only — real secret comes from deploy.sh)

```yaml
# Created automatically by deploy.sh from your .env — do not apply this file.
apiVersion: v1
kind: Secret
metadata:
  name: elastic-credentials
  namespace: synthetic-network
stringData:
  ES_URL: https://<project>.es.<region>.elastic.cloud
  KIBANA_URL: https://<project>.kb.<region>.elastic.cloud
  ELASTIC_API_KEY: <api key>
```

- [ ] **Step 4: Write `k8s/jobs/fleet-setup.yaml`**

```yaml
apiVersion: batch/v1
kind: Job
metadata:
  name: fleet-setup
  namespace: synthetic-network
spec:
  backoffLimit: 3
  template:
    spec:
      serviceAccountName: fleet-setup
      restartPolicy: Never
      containers:
        - name: fleet-setup
          image: kennethfoo24/synthetic-netgen:latest
          command: ["python", "-m", "synthsetup.fleet_setup"]
          envFrom:
            - secretRef: {name: elastic-credentials}
          env:
            - name: K8S_NAMESPACE
              value: synthetic-network
```

- [ ] **Step 5: Write `k8s/elastic-agent.yaml`**

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: elastic-agent
  namespace: synthetic-network
spec:
  replicas: 1
  selector:
    matchLabels: {app: elastic-agent}
  template:
    metadata:
      labels: {app: elastic-agent}
    spec:
      containers:
        - name: elastic-agent
          image: docker.elastic.co/elastic-agent/elastic-agent:9.1.3
          env:
            - name: FLEET_ENROLL
              value: "1"
            - name: FLEET_URL
              valueFrom:
                secretKeyRef: {name: agent-enrollment, key: FLEET_URL}
            - name: FLEET_ENROLLMENT_TOKEN
              valueFrom:
                secretKeyRef: {name: agent-enrollment, key: FLEET_ENROLLMENT_TOKEN}
          ports:
            - {containerPort: 9001, protocol: UDP, name: asa-syslog}
          resources:
            requests: {cpu: 200m, memory: 512Mi}
            limits: {memory: 1Gi}
---
apiVersion: v1
kind: Service
metadata:
  name: elastic-agent
  namespace: synthetic-network
spec:
  selector: {app: elastic-agent}
  ports:
    - {name: asa-syslog, port: 9001, protocol: UDP, targetPort: 9001}
```

Note: check the highest agent version supported by the serverless project (`GET $KIBANA_URL/api/fleet/agents/available_versions`) and pin that instead of 9.1.3 if it differs.

- [ ] **Step 6: Write `k8s/generators/syslog-gen.yaml`**

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: syslog-gen
  namespace: synthetic-network
spec:
  replicas: 1
  selector:
    matchLabels: {app: syslog-gen}
  template:
    metadata:
      labels: {app: syslog-gen}
    spec:
      containers:
        - name: syslog-gen
          image: kennethfoo24/synthetic-netgen:latest
          args:
            - syslog-asa
            - --target-host=elastic-agent
            - --target-port=9001
            - --topology=/app/topology/network.yaml
          resources:
            requests: {cpu: 50m, memory: 128Mi}
            limits: {memory: 256Mi}
```

- [ ] **Step 7: Write `k8s/kustomization.yaml`**

```yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
resources:
  - namespace.yaml
  - rbac.yaml
  - jobs/fleet-setup.yaml
  - elastic-agent.yaml
  - generators/syslog-gen.yaml
```

- [ ] **Step 8: Verify manifests build**

Run: `kubectl kustomize k8s/ > /dev/null && echo OK` — Expected: `OK`.

- [ ] **Step 9: Commit**

```bash
git add -A && git commit -m "feat: k8s manifests — agent, syslog-gen, fleet-setup job, rbac"
```

---

### Task 9: `deploy.sh` + `Makefile`

**Files:**
- Create: `deploy.sh` (executable), `Makefile`

**Interfaces:**
- Consumes: `.env` (ES_URL, KIBANA_URL, ELASTIC_API_KEY); `kubectl` context pointed at the user's cluster; manifests from Task 8.
- Produces: `make up`, `make down`, `make validate` targets used by all later plans.

- [ ] **Step 1: Write `deploy.sh`**

```bash
#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

[ -f .env ] || { echo "ERROR: .env missing (copy .env.example)"; exit 1; }
set -a; source .env; set +a
for v in ES_URL KIBANA_URL ELASTIC_API_KEY; do
  [ -n "${!v:-}" ] || { echo "ERROR: $v not set in .env"; exit 1; }
done

echo "==> namespace + credentials"
kubectl apply -f k8s/namespace.yaml
kubectl -n synthetic-network create secret generic elastic-credentials \
  --from-literal=ES_URL="$ES_URL" \
  --from-literal=KIBANA_URL="$KIBANA_URL" \
  --from-literal=ELASTIC_API_KEY="$ELASTIC_API_KEY" \
  --dry-run=client -o yaml | kubectl apply -f -

echo "==> fleet setup job"
kubectl apply -f k8s/rbac.yaml
kubectl -n synthetic-network delete job fleet-setup --ignore-not-found
kubectl apply -f k8s/jobs/fleet-setup.yaml
kubectl -n synthetic-network wait --for=condition=complete job/fleet-setup --timeout=300s || {
  echo "ERROR: fleet-setup failed; logs:"; kubectl -n synthetic-network logs job/fleet-setup; exit 1;
}
kubectl -n synthetic-network logs job/fleet-setup

echo "==> agent + generators"
kubectl apply -f k8s/elastic-agent.yaml
kubectl apply -f k8s/generators/syslog-gen.yaml
kubectl -n synthetic-network rollout status deploy/elastic-agent --timeout=300s
kubectl -n synthetic-network rollout status deploy/syslog-gen --timeout=120s

echo "==> done. Run 'make validate' in ~2 minutes to confirm data is flowing."
```

- [ ] **Step 2: Write `Makefile`**

```makefile
.PHONY: up down validate test

up:
	./deploy.sh

down:
	kubectl delete namespace synthetic-network --ignore-not-found

validate:
	set -a; . ./.env; set +a; .venv/bin/python -m synthsetup.validate

test:
	.venv/bin/ruff check . && .venv/bin/pytest -v
```

- [ ] **Step 3: Verify script hygiene**

Run: `chmod +x deploy.sh && bash -n deploy.sh && make -n up && echo OK` — Expected: `OK`.

- [ ] **Step 4: Commit**

```bash
git add -A && git commit -m "feat: one-command deploy (deploy.sh + Makefile)"
```

---

### Task 10: Validation script + live end-to-end verification

**Files:**
- Create: `src/synthsetup/validate.py`
- Test: `tests/test_validate.py`

**Interfaces:**
- Consumes: env `ES_URL`, `KIBANA_URL`, `ELASTIC_API_KEY`.
- Produces: `python -m synthsetup.validate` — prints a ✅/❌ report and exits nonzero on any failure. Checks list `CHECKS: list[tuple[str, Callable[[Ctx], str]]]` is extended by later plans (one check per data stream).

- [ ] **Step 1: Write the failing tests**

`tests/test_validate.py`:
```python
import httpx
import respx
from synthsetup.validate import check_asa_docs_recent, check_agents_online, Ctx

CTX = Ctx(es_url="https://es.example.com", kibana_url="https://kb.example.com", api_key="k")

@respx.mock
def test_asa_check_passes_with_recent_docs():
    respx.post("https://es.example.com/logs-cisco_asa.log-default/_count").respond(
        json={"count": 42})
    assert "42" in check_asa_docs_recent(CTX)

@respx.mock
def test_asa_check_fails_with_zero_docs():
    respx.post("https://es.example.com/logs-cisco_asa.log-default/_count").respond(
        json={"count": 0})
    try:
        check_asa_docs_recent(CTX)
        assert False, "should have raised"
    except AssertionError:
        raise
    except Exception as exc:
        assert "0 docs" in str(exc)

@respx.mock
def test_agents_online():
    respx.get("https://kb.example.com/api/fleet/agents").respond(
        json={"items": [{"status": "online", "policy_id": "p"}], "total": 1})
    assert "online" in check_agents_online(CTX)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_validate.py -v` — Expected: FAIL.

- [ ] **Step 3: Write `src/synthsetup/validate.py`**

```python
from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from typing import Callable

import httpx


@dataclass
class Ctx:
    es_url: str
    kibana_url: str
    api_key: str

    def es(self) -> httpx.Client:
        return httpx.Client(base_url=self.es_url.rstrip("/"),
                            headers={"Authorization": f"ApiKey {self.api_key}"}, timeout=30)

    def kb(self) -> httpx.Client:
        return httpx.Client(base_url=self.kibana_url.rstrip("/"),
                            headers={"Authorization": f"ApiKey {self.api_key}",
                                     "kbn-xsrf": "true"}, timeout=30)


class CheckFailed(Exception):
    pass


def check_asa_docs_recent(ctx: Ctx) -> str:
    r = ctx.es().post("/logs-cisco_asa.log-default/_count", json={
        "query": {"range": {"@timestamp": {"gte": "now-5m"}}}})
    if r.status_code == 404:
        raise CheckFailed("data stream logs-cisco_asa.log-default does not exist")
    count = r.json().get("count", 0)
    if count == 0:
        raise CheckFailed("0 docs in logs-cisco_asa.log-default in last 5m")
    return f"{count} ASA docs in last 5m"


def check_agents_online(ctx: Ctx) -> str:
    r = ctx.kb().get("/api/fleet/agents", params={"kuery": "status:online"})
    items = r.json().get("items", [])
    if not items:
        raise CheckFailed("no online agents in Fleet")
    return f"{len(items)} agent(s) online"


CHECKS: list[tuple[str, Callable[[Ctx], str]]] = [
    ("agent online in Fleet", check_agents_online),
    ("ASA logs flowing", check_asa_docs_recent),
]


def main() -> None:
    ctx = Ctx(os.environ["ES_URL"], os.environ["KIBANA_URL"], os.environ["ELASTIC_API_KEY"])
    failed = 0
    for name, fn in CHECKS:
        try:
            detail = fn(ctx)
            print(f"  ✅ {name}: {detail}")
        except Exception as exc:
            print(f"  ❌ {name}: {exc}")
            failed += 1
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_validate.py -v` — Expected: 3 PASS.

- [ ] **Step 5: Live end-to-end run (requires user's cluster + serverless project)**

```bash
make up          # full deploy: fleet-setup → agent → generator
sleep 120
make validate    # expect both checks ✅
```
Expected: both checks pass. If fleet-setup fails, its logs name the exact Fleet API call — most likely fix is the `CISCO_ASA_INPUTS` keys (see Task 7 Step 6).

- [ ] **Step 6: Dashboard verification (human step)**

**ASK THE USER** to open Kibana → Dashboards → search "ASA" → open **[Logs Cisco ASA] Overview** and confirm panels are populating (events over time, top source IPs, denied connections). This is the acceptance gate for the whole vertical slice.

- [ ] **Step 7: Commit + push**

```bash
git add -A && git commit -m "feat: validation checks (agent online, ASA data flowing)"
git push origin main
```

---

## Verification checklist (plan-level)

- `make test` green (all unit tests + ruff)
- CI green on `main`; `kennethfoo24/synthetic-netgen:latest` pullable from Docker Hub
- `make up` from a clean namespace completes without manual steps (besides `.env`)
- `make validate` shows both ✅
- [Logs Cisco ASA] dashboard populates within ~2 minutes of deploy
- `make down` then `make up` again works (reproducibility)
