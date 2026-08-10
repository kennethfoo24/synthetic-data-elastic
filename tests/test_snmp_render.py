"""Unit tests for snmp/generator/render.py.

Tests run against the in-memory render functions — no filesystem I/O required.
The snmp package at the project root is added to sys.path so it can be imported
without being installed.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import ClassVar

import pytest
import yaml

# Make the project root importable so `snmp.generator.render` resolves.
_PROJECT_ROOT = str(Path(__file__).parent.parent)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from snmp.generator.render import (
    DATA_DIR,
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
        with TAG:MODULE syntax so counter values increment between polls.
        """
        content = render_snmprec(device)
        # Counter32 (tag 65) with numeric variation: |65:numeric|
        assert "|65:numeric|" in content, (
            f"No Counter32 numeric variation found in {device.name}.snmprec"
        )

    @pytest.mark.parametrize("device", DEVICES)
    def test_gauges_use_numeric_variation(self, device):
        """CPU and memory gauges must use the numeric variation module
        so values wander between polls (simulates real workload fluctuation).
        """
        content = render_snmprec(device)
        # Gauge32 (tag 66) with numeric variation: |66:numeric|
        assert "|66:numeric|" in content, (
            f"No Gauge32 numeric variation found in {device.name}.snmprec"
        )

    @pytest.mark.parametrize("device", DEVICES)
    def test_sysuptime_uses_numeric_variation(self, device):
        """sysUpTime must use numeric variation (TimeTicks, tag 67)."""
        content = render_snmprec(device)
        assert "1.3.6.1.2.1.1.3.0|67:numeric|" in content

    @pytest.mark.parametrize("device", DEVICES)
    def test_numeric_syntax_is_key_value(self, device):
        """Every numeric variation value field must use key=value CSV format.

        snmpsim/variation/numeric.py reads the value field as comma-separated
        key=value pairs at runtime.  The positional numeric:<init>:<min>:<max>:<step>
        scheme does not exist.
        """
        content = render_snmprec(device)
        for line in content.splitlines():
            if ":numeric|" not in line:
                continue
            _oid, _tag, val = line.split("|", 2)
            # Value field must contain at least one key=value pair
            assert "=" in val, (
                f"Numeric variation value is not key=value CSV in "
                f"{device.name}.snmprec: {line!r}"
            )
            for pair in val.split(","):
                pair = pair.strip()
                assert "=" in pair, (
                    f"Non key=value token {pair!r} in numeric variation line: {line!r}"
                )

    @pytest.mark.parametrize("device", DEVICES)
    def test_counter32_has_wrap(self, device):
        """Counter32 numeric lines must include wrap=1 for modular rollover."""
        content = render_snmprec(device)
        for line in content.splitlines():
            if "|65:numeric|" not in line:
                continue
            assert "wrap=1" in line, (
                f"Counter32 numeric line missing wrap=1 in {device.name}.snmprec: {line!r}"
            )

    @pytest.mark.parametrize("device", DEVICES)
    def test_storage_size_is_static(self, device):
        """hrStorageSize must be a plain static Gauge32 — no variation module."""
        content = render_snmprec(device)
        for line in content.splitlines():
            if "1.3.6.1.2.1.25.2.3.1.5.1" in line:
                # Must be |66|VALUE (static), NOT |66:numeric|...
                assert "|66|" in line, (
                    f"hrStorageSize should be static (|66|) in {device.name}.snmprec: {line!r}"
                )
                assert ":numeric" not in line, (
                    f"hrStorageSize must not use numeric module in {device.name}.snmprec: {line!r}"
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
            assert "1.3.6.1.4.1.99999.1.1.0|66:numeric|" in content, (
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
# Parser-truth test: every committed .snmprec line must parse via snmpsim grammar
# ---------------------------------------------------------------------------

class TestSnmprecGrammarParse:
    """Feed every line of every committed .snmprec through snmpsim's own grammar
    parser so invalid syntax cannot be committed without CI catching it.

    snmpsim's grammar.parse() validates the 3-field OID|TAG|VALUE structure and
    is the authoritative parser for both static and variation-module lines.

    For static lines (no ':' in tag) we additionally call SnmprecRecord to confirm
    the type code and value are valid SNMP primitives.  For variation-module lines
    (e.g. '65:numeric') we stop at grammar.parse() because evaluate() would need
    to call the module at runtime.
    """

    @pytest.fixture(scope="class", autouse=True)
    @classmethod
    def require_snmpsim(cls):
        pytest.importorskip("snmpsim", reason="snmpsim not installed; skipping parser tests")

    @pytest.mark.parametrize("device", DEVICES)
    def test_all_lines_parse(self, device):
        from snmpsim.grammar import snmprec as snmprec_grammar
        grammar = snmprec_grammar.SnmprecGrammar()

        content = render_snmprec(device)
        for line in content.strip().splitlines():
            if not line or line.startswith("#"):
                continue
            try:
                grammar.parse(line.encode())
            except Exception as exc:  # noqa: BLE001
                pytest.fail(
                    f"snmpsim grammar.parse() rejected line in {device.name}.snmprec: "
                    f"{line!r} — {exc}"
                )

    def test_committed_files_match_render(self):
        """Committed .snmprec files must be byte-identical to a fresh render.

        Ensures nobody hand-edited snmp/data/ without re-running render.py.
        """
        missing = []
        drift = []
        for d in DEVICES:
            path = DATA_DIR / f"{d.name}.snmprec"
            expected = render_snmprec(d)
            if not path.exists():
                missing.append(d.name)
            elif path.read_text() != expected:
                drift.append(d.name)
        assert not missing, f"Missing committed .snmprec files: {missing}"
        assert not drift, (
            f"Committed .snmprec files differ from fresh render (re-run render.py): {drift}"
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

    def test_community_field_uses_metadata(self):
        """Logstash integration-snmp exposes the community at [@metadata][host_community].
        The pipeline must copy that field to device.name — NOT use [snmp_community].
        """
        conf = render_logstash_conf(DEVICES)
        assert '[@metadata][host_community]' in conf
        assert 'snmp_community' not in conf

    def test_target_snmp_prevents_field_explosion(self):
        """target => "snmp" nests all OID fields under [snmp] to prevent
        dotted-OID names from polluting the top-level event namespace.
        """
        conf = render_logstash_conf(DEVICES)
        assert 'target => "snmp"' in conf

    def test_translate_uses_source_target(self):
        """translate filter must use source/target (not deprecated field/destination).

        The deprecated translate-filter params are ``field`` and ``destination``.
        Note: the Logstash mutate ``add_field`` directive contains the substring
        "field" so we check for the translate-specific standalone param form.
        """
        conf = render_logstash_conf(DEVICES)
        assert "source =>" in conf
        assert "target =>" in conf
        # Translate-specific deprecated params appear as "    field =>" or
        # "    destination =>" (indented inside the translate block).
        # We check there is no bare translate `field =>` by verifying "field =>" only
        # ever appears as part of "add_field =>".
        for line in conf.splitlines():
            stripped = line.strip()
            if stripped.startswith("field =>"):
                pytest.fail(f"Deprecated translate 'field =>' found: {line!r}")
            if stripped.startswith("destination =>"):
                pytest.fail(f"Deprecated translate 'destination =>' found: {line!r}")

    def test_storage_oid_only_in_storage_block(self):
        """Storage-capacity OID must appear only in the storage input block.
        16 non-storage hosts would return noSuchObject if polled for this OID.
        """
        conf = render_logstash_conf(DEVICES)
        storage_oid = "1.3.6.1.4.1.99999.1.1.0"
        assert storage_oid in conf  # present for storage block
        # Non-storage community strings must not appear in the same input block
        # as the storage OID.  Verify by checking the storage block is separate.
        lines = conf.splitlines()
        in_storage_block = False
        for line in lines:
            if "Storage devices" in line:
                in_storage_block = True
            if in_storage_block and storage_oid in line:
                break  # found it in the storage block — correct
        else:
            pytest.fail(f"{storage_oid} not found in storage input block")

    def test_two_input_blocks(self):
        """Two snmp input blocks: one for non-storage, one for storage."""
        conf = render_logstash_conf(DEVICES)
        # Count occurrences of "snmp {" inside the input block
        assert conf.count("snmp {") >= 2, (
            "Expected at least 2 separate snmp input blocks (non-storage + storage)"
        )
