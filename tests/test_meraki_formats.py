"""Unit tests for Cisco Meraki syslog wire format builders.

All tests match the exact output string so regressions in field order or
whitespace are caught immediately.
"""
from __future__ import annotations

from datetime import UTC, datetime

from synthgen.syslog_gen.formats.meraki import (
    meraki_event_association,
    meraki_event_disassociation,
    meraki_flow,
    meraki_url,
)

# Fixed timestamp: microsecond=0 so the fractional part is deterministically zero.
_TS = datetime(2026, 8, 11, 12, 0, 0, tzinfo=UTC)
_EPOCH = int(_TS.timestamp())  # e.g. 1754906400


# ---------------------------------------------------------------------------
# flows
# ---------------------------------------------------------------------------

def test_meraki_flow_exact_string():
    line = meraki_flow(_TS, "meraki-mx-01", "10.10.3.11", 51234, "10.10.5.11", 443)
    assert line == (
        f"<134>1 {_EPOCH}.000000000 meraki-mx-01 flows "
        "src=10.10.3.11 dst=10.10.5.11 protocol=tcp "
        "sport=51234 dport=443 pattern: allow all"
    )


def test_meraki_flow_deny_pattern():
    line = meraki_flow(
        _TS, "meraki-mx-01", "203.0.113.5", 33333, "10.10.5.11", 80,
        protocol="tcp", pattern="deny all",
    )
    assert "pattern: deny all" in line
    assert "protocol=tcp" in line


def test_meraki_flow_udp_protocol():
    line = meraki_flow(_TS, "meraki-mx-01", "10.0.0.1", 1000, "10.0.0.2", 53, protocol="udp")
    assert "protocol=udp" in line


def test_meraki_flow_priority_and_version():
    line = meraki_flow(_TS, "meraki-mx-01", "1.2.3.4", 1024, "5.6.7.8", 443)
    assert line.startswith("<134>1 ")


def test_meraki_flow_timestamp_epoch_format():
    # Fractional part must be 9 digits.
    line = meraki_flow(_TS, "meraki-mx-01", "1.2.3.4", 1024, "5.6.7.8", 443)
    ts_token = line.split()[1]
    epoch_str, frac_str = ts_token.split(".")
    assert epoch_str == str(_EPOCH)
    assert len(frac_str) == 9


def test_meraki_flow_microsecond_in_fractional():
    ts = datetime(2026, 8, 11, 12, 0, 0, 123456, tzinfo=UTC)
    line = meraki_flow(ts, "meraki-mx-01", "1.2.3.4", 1024, "5.6.7.8", 443)
    ts_token = line.split()[1]
    _, frac_str = ts_token.split(".")
    assert frac_str == "123456000"


# ---------------------------------------------------------------------------
# urls
# ---------------------------------------------------------------------------

def test_meraki_url_exact_string():
    line = meraki_url(
        _TS, "meraki-mx-01",
        "10.10.3.11", 51234, "10.10.5.11", 443,
        "AA:BB:CC:DD:EE:01", "GET", "https://cdn.example.com/asset.js",
    )
    assert line == (
        f"<134>1 {_EPOCH}.000000000 meraki-mx-01 urls "
        "src=10.10.3.11:51234 dst=10.10.5.11:443 "
        "mac=AA:BB:CC:DD:EE:01 request: GET https://cdn.example.com/asset.js"
    )


def test_meraki_url_msg_type_is_urls():
    line = meraki_url(
        _TS, "meraki-mx-01", "1.2.3.4", 80, "5.6.7.8", 443,
        "00:11:22:33:44:55", "POST", "https://api.example.com/",
    )
    parts = line.split()
    # parts[3] is the msg_type token
    assert parts[3] == "urls"


# ---------------------------------------------------------------------------
# events: association
# ---------------------------------------------------------------------------

def test_meraki_event_association_exact_string():
    line = meraki_event_association(_TS, "meraki-ap-01", 0, 1, "AA:BB:CC:DD:EE:02")
    assert line == (
        f"<134>1 {_EPOCH}.000000000 meraki-ap-01 events "
        "type=association radio='0' vap='1' client_mac='AA:BB:CC:DD:EE:02'"
    )


def test_meraki_event_association_msg_type_is_events():
    line = meraki_event_association(_TS, "meraki-ap-01", 1, 2, "00:11:22:33:44:55")
    assert line.split()[3] == "events"


def test_meraki_event_association_radio_and_vap_quoted():
    line = meraki_event_association(_TS, "meraki-ap-02", 1, 3, "FF:EE:DD:CC:BB:AA")
    assert "radio='1'" in line
    assert "vap='3'" in line


# ---------------------------------------------------------------------------
# events: disassociation
# ---------------------------------------------------------------------------

def test_meraki_event_disassociation_exact_string():
    line = meraki_event_disassociation(_TS, "meraki-ap-01", 0, 1, "AA:BB:CC:DD:EE:02")
    assert line == (
        f"<134>1 {_EPOCH}.000000000 meraki-ap-01 events "
        "type=disassociation radio='0' vap='1' client_mac='AA:BB:CC:DD:EE:02' reason=1"
    )


def test_meraki_event_disassociation_custom_reason():
    line = meraki_event_disassociation(_TS, "meraki-ap-01", 0, 0, "AA:BB:CC:DD:EE:03", reason=7)
    assert "reason=7" in line
    assert "type=disassociation" in line
