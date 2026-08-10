"""Unit tests for snmp/generator/render.py.

Tests run against the in-memory render functions — no filesystem I/O required.
The snmp package at the project root is added to sys.path so it can be imported
without being installed.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

# Make the project root importable so `snmp.generator.render` resolves.
_PROJECT_ROOT = str(Path(__file__).parent.parent)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from snmp.generator.render import (
    TOPOLOGY_PATH,
    _snmp_devices,
    render_logstash_conf,
    render_snmprec,
    render_translate_yaml,
)

# ---------------------------------------------------------------------------
# Fixtures / constants
# ---------------------------------------------------------------------------

DEVICES = _snmp_devices(TOPOLOGY_PATH)
DEVICE_NAMES = {d.name for d in DEVICES}


# ---------------------------------------------------------------------------
# Device enumeration
# ---------------------------------------------------------------------------

class TestSnmpDeviceList:
    def test_count_excludes_database_and_meraki(self):
        """Non-database, non-meraki devices: topology has 20 eligible devices."""
        assert len(DEVICES) >= 18, f"Expected ≥18 SNMP devices, got {len(DEVICES)}"

    def test_no_database_devices(self):
        assert not any(d.role == "database" for d in DEVICES)

    def test_no_meraki_devices(self):
        assert not any(d.vendor == "meraki" for d in DEVICES)

    def test_file_per_device(self):
        """Every eligible device must produce a .snmprec (unique name = unique file)."""
        assert len(DEVICE_NAMES) == len(DEVICES), "Duplicate device names detected"


# ---------------------------------------------------------------------------
# sysName correctness
# ---------------------------------------------------------------------------

class TestSysName:
    @pytest.mark.parametrize("device", DEVICES)
    def test_sysname_equals_device_name(self, device):
        """sysName (OID 1.3.6.1.2.1.1.5.0) must equal the topology device name
        so the MCP app can resolve node identity from SNMP data.
        """
        content = render_snmprec(device)
        # sysName is OCTET STRING (tag 4) — hex-encoded ASCII
        expected_hex = device.name.encode("ascii").hex()
        sysname_line = f"1.3.6.1.2.1.1.5.0|4|{expected_hex}"
        assert sysname_line in content, (
            f"sysName for {device.name!r} is not {device.name!r}"
        )


# ---------------------------------------------------------------------------
# Numeric variation module syntax
# ---------------------------------------------------------------------------

class TestNumericModuleSyntax:
    @pytest.mark.parametrize("device", DEVICES)
    def test_counters_use_numeric_variation(self, device):
        """ifInOctets and ifOutOctets must use snmpsim's numeric variation module
        so counter values increment between polls (simulates traffic flow).
        """
        content = render_snmprec(device)
        # Counter32 (tag 65) with numeric variation
        assert "|65|numeric:" in content, (
            f"No Counter32 numeric variation found in {device.name}.snmprec"
        )

    @pytest.mark.parametrize("device", DEVICES)
    def test_gauges_use_numeric_variation(self, device):
        """CPU and memory gauges must use the numeric variation module
        so values wander between polls (simulates real workload fluctuation).
        """
        content = render_snmprec(device)
        # Gauge32 (tag 66) with numeric variation
        assert "|66|numeric:" in content, (
            f"No Gauge32 numeric variation found in {device.name}.snmprec"
        )

    @pytest.mark.parametrize("device", DEVICES)
    def test_sysuptime_uses_numeric_variation(self, device):
        """sysUpTime must use numeric variation (TimeTicks, tag 67)."""
        content = render_snmprec(device)
        assert "1.3.6.1.2.1.1.3.0|67|numeric:" in content

    @pytest.mark.parametrize("device", DEVICES)
    def test_numeric_syntax_has_four_fields(self, device):
        """Every numeric variation entry must have 4 colon-separated fields:
        numeric:<initial>:<min>:<max>:<step>.
        """
        content = render_snmprec(device)
        for line in content.splitlines():
            if "|numeric:" not in line:
                continue
            _oid, _tag, val = line.split("|", 2)
            parts = val.split(":")
            assert len(parts) == 5, (  # "numeric" + 4 numeric fields
                f"Bad numeric syntax in {device.name}.snmprec: {line!r}"
            )


# ---------------------------------------------------------------------------
# Storage-specific OID
# ---------------------------------------------------------------------------

class TestStorageOid:
    def test_storage_devices_have_capacity_oid(self):
        storage_devs = [d for d in DEVICES if d.role == "storage"]
        assert storage_devs, "No storage devices in SNMP device list"
        for d in storage_devs:
            content = render_snmprec(d)
            assert "1.3.6.1.4.1.99999.1.1.0|66|numeric:" in content, (
                f"Storage device {d.name} missing capacity-percent OID"
            )

    def test_non_storage_devices_lack_capacity_oid(self):
        for d in DEVICES:
            if d.role == "storage":
                continue
            content = render_snmprec(d)
            assert "1.3.6.1.4.1.99999.1.1.0" not in content, (
                f"Non-storage device {d.name} unexpectedly has capacity-percent OID"
            )


# ---------------------------------------------------------------------------
# Interface count by role
# ---------------------------------------------------------------------------

class TestIfaceCount:
    from typing import ClassVar
    _EXPECTED: ClassVar[dict[str, int]] = {
        "router": 6, "switch": 8, "firewall": 4, "server": 2, "storage": 2
    }

    @pytest.mark.parametrize("device", DEVICES)
    def test_iface_count_matches_role(self, device):
        expected_n = self._EXPECTED.get(device.role, 2)
        content = render_snmprec(device)
        # Count ifIndex rows (1.3.6.1.2.1.2.2.1.1.<i>)
        iface_lines = [
            ln for ln in content.splitlines()
            if ln.startswith("1.3.6.1.2.1.2.2.1.1.")
        ]
        assert len(iface_lines) == expected_n, (
            f"{device.name} ({device.role}): expected {expected_n} interfaces, "
            f"got {len(iface_lines)}"
        )


# ---------------------------------------------------------------------------
# OID ordering
# ---------------------------------------------------------------------------

class TestOidOrdering:
    @pytest.mark.parametrize("device", DEVICES)
    def test_oids_are_sorted(self, device):
        """snmpsim requires OIDs in ascending numerical order."""
        content = render_snmprec(device)
        oids = []
        for line in content.strip().splitlines():
            oid_str = line.split("|")[0]
            oids.append(tuple(int(x) for x in oid_str.split(".")))
        assert oids == sorted(oids), (
            f"OIDs in {device.name}.snmprec are not in ascending order"
        )


# ---------------------------------------------------------------------------
# translate.yaml completeness
# ---------------------------------------------------------------------------

class TestTranslateYaml:
    def test_all_devices_present(self):
        """translate.yaml must contain every SNMP device."""
        raw = render_translate_yaml(DEVICES)
        parsed = yaml.safe_load(raw)
        assert "devices" in parsed
        translate_names = set(parsed["devices"].keys())
        assert translate_names == DEVICE_NAMES, (
            f"Missing: {DEVICE_NAMES - translate_names}, "
            f"Extra: {translate_names - DEVICE_NAMES}"
        )

    def test_each_entry_has_required_fields(self):
        raw = render_translate_yaml(DEVICES)
        parsed = yaml.safe_load(raw)
        required = {"vendor", "role", "site", "ip"}
        for name, info in parsed["devices"].items():
            missing = required - set(info.keys())
            assert not missing, f"translate entry {name!r} missing fields: {missing}"

    def test_vendor_role_site_match_topology(self):
        raw = render_translate_yaml(DEVICES)
        parsed = yaml.safe_load(raw)["devices"]
        device_by_name = {d.name: d for d in DEVICES}
        for name, info in parsed.items():
            d = device_by_name[name]
            assert info["vendor"] == d.vendor
            assert info["role"] == d.role
            assert info["site"] == d.site
            assert info["ip"] == d.ip


# ---------------------------------------------------------------------------
# logstash.conf sanity
# ---------------------------------------------------------------------------

class TestLogstashConf:
    def test_all_devices_have_host_entry(self):
        conf = render_logstash_conf(DEVICES)
        for name in DEVICE_NAMES:
            assert f'community => "{name}"' in conf, (
                f"Device {name!r} missing from Logstash snmp input hosts"
            )

    def test_snmpsim_target(self):
        conf = render_logstash_conf(DEVICES)
        assert "udp:snmpsim/161" in conf

    def test_data_stream_config(self):
        conf = render_logstash_conf(DEVICES)
        assert 'data_stream_type      => "metrics"' in conf
        assert 'data_stream_dataset   => "snmp.device"' in conf
        assert 'data_stream_namespace => "default"' in conf

    def test_api_key_env_var_reference(self):
        conf = render_logstash_conf(DEVICES)
        assert "${LS_API_KEY}" in conf
        assert "${LS_ES_URL}" in conf
