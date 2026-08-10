"""Unit tests for formats/panw.py — PAN-OS TRAFFIC and THREAT CSV formatters.

Tests assert:
  - Header shape (PRI=14, hostname present, syslog timestamp format)
  - Field COUNT pinned at TRAFFIC=67 / THREAT=78
  - Key field positions (type@3, subtype@4, src_ip@7, dst_ip@8, proto@29)
  - Determinism (same inputs → identical output)
  - PAN-OS timestamp format (YYYY/MM/DD HH:MM:SS)
  - RFC 3164 timestamp in header (no year)
"""
from __future__ import annotations

import re
from datetime import UTC, datetime

from synthgen.syslog_gen.formats import panw

TS = datetime(2026, 8, 11, 12, 34, 56, 0, tzinfo=UTC)
HOSTNAME = "palo-fw-prod"
SERIAL = "001901000001"

# Pinned counts — update here (and the assert in panw.py) if the simulate gate
# reports a different expected count.
TRAFFIC_FIELD_COUNT = 67
THREAT_FIELD_COUNT = 78


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _csv_fields(msg: str) -> list[str]:
    """Strip the RFC 3164 syslog header and return the CSV fields as a list.

    Expected header: ``<pri>Mmm DD HH:MM:SS hostname csv...``
    """
    # Space-padded day means "Aug  1" is valid; use \\s+ between month and day.
    match = re.match(r"^<\d+>\w{3}\s+\d{1,2} \d{2}:\d{2}:\d{2} \S+ (.+)$", msg)
    assert match, f"Could not parse syslog header: {msg!r}"
    return match.group(1).split(",")


# ---------------------------------------------------------------------------
# TRAFFIC log tests
# ---------------------------------------------------------------------------

def test_traffic_header_starts_with_pri14():
    msg = panw.panos_traffic(TS, HOSTNAME, SERIAL,
                             "10.10.5.11", "10.20.0.1",
                             45678, 4500, "udp",
                             100_000, 60_000, 40_000)
    assert msg.startswith("<14>"), f"Expected <14> PRI, got: {msg[:10]}"


def test_traffic_header_contains_hostname():
    msg = panw.panos_traffic(TS, HOSTNAME, SERIAL,
                             "10.10.5.11", "10.20.0.1",
                             45678, 4500, "udp",
                             100_000, 60_000, 40_000)
    assert HOSTNAME in msg


def test_traffic_field_count():
    msg = panw.panos_traffic(TS, HOSTNAME, SERIAL,
                             "10.10.5.11", "10.20.0.1",
                             45678, 4500, "udp",
                             100_000, 60_000, 40_000)
    fields = _csv_fields(msg)
    assert len(fields) == TRAFFIC_FIELD_COUNT, (
        f"Expected {TRAFFIC_FIELD_COUNT} CSV fields, got {len(fields)}\n"
        f"Fields: {fields}"
    )


def test_traffic_key_positions():
    msg = panw.panos_traffic(TS, HOSTNAME, SERIAL,
                             "10.10.5.11", "10.20.0.1",
                             45678, 4500, "udp",
                             100_000, 60_000, 40_000)
    f = _csv_fields(msg)
    assert f[3] == "TRAFFIC",     f"[3] type expected TRAFFIC, got {f[3]!r}"
    assert f[4] == "end",         f"[4] subtype expected end, got {f[4]!r}"
    assert f[7] == "10.10.5.11", f"[7] src_ip expected 10.10.5.11, got {f[7]!r}"
    assert f[8] == "10.20.0.1",  f"[8] dst_ip expected 10.20.0.1, got {f[8]!r}"
    assert f[29] == "udp",        f"[29] proto expected udp, got {f[29]!r}"


def test_traffic_zones_assigned():
    msg = panw.panos_traffic(TS, HOSTNAME, SERIAL,
                             "10.10.5.11", "10.20.0.1",
                             45678, 4500, "udp",
                             100_000, 60_000, 40_000,
                             src_zone="inside", dst_zone="outside")
    f = _csv_fields(msg)
    assert f[16] == "inside",  f"[16] src_zone expected inside, got {f[16]!r}"
    assert f[17] == "outside", f"[17] dst_zone expected outside, got {f[17]!r}"


def test_traffic_determinism():
    kwargs = {
        "ts": TS, "hostname": HOSTNAME, "serial": SERIAL,
        "src_ip": "10.10.5.11", "dst_ip": "10.20.0.1",
        "src_port": 45678, "dst_port": 4500, "proto": "udp",
        "bytes_total": 100_000, "bytes_sent": 60_000, "bytes_received": 40_000,
    }
    assert panw.panos_traffic(**kwargs) == panw.panos_traffic(**kwargs)


# ---------------------------------------------------------------------------
# THREAT log tests
# ---------------------------------------------------------------------------

def test_threat_header_starts_with_pri14():
    msg = panw.panos_threat(TS, HOSTNAME, SERIAL,
                            "203.0.113.5", "10.10.5.11",
                            44321, 443, "tcp")
    assert msg.startswith("<14>"), f"Expected <14> PRI, got: {msg[:10]}"


def test_threat_field_count():
    msg = panw.panos_threat(TS, HOSTNAME, SERIAL,
                            "203.0.113.5", "10.10.5.11",
                            44321, 443, "tcp")
    fields = _csv_fields(msg)
    assert len(fields) == THREAT_FIELD_COUNT, (
        f"Expected {THREAT_FIELD_COUNT} CSV fields, got {len(fields)}\n"
        f"Fields: {fields}"
    )


def test_threat_key_positions():
    msg = panw.panos_threat(TS, HOSTNAME, SERIAL,
                            "203.0.113.5", "10.10.5.11",
                            44321, 443, "tcp",
                            subtype="vulnerability")
    f = _csv_fields(msg)
    assert f[3] == "THREAT",          f"[3] type expected THREAT, got {f[3]!r}"
    assert f[4] == "vulnerability",   f"[4] subtype expected vulnerability, got {f[4]!r}"
    assert f[7] == "203.0.113.5",    f"[7] src_ip expected 203.0.113.5, got {f[7]!r}"
    assert f[8] == "10.10.5.11",     f"[8] dst_ip expected 10.10.5.11, got {f[8]!r}"
    assert f[29] == "tcp",            f"[29] proto expected tcp, got {f[29]!r}"


def test_threat_key_positions_spyware():
    msg = panw.panos_threat(TS, HOSTNAME, SERIAL,
                            "203.0.113.5", "10.10.5.11",
                            44321, 443, "tcp",
                            subtype="spyware")
    f = _csv_fields(msg)
    assert f[4] == "spyware", f"[4] subtype expected spyware, got {f[4]!r}"


def test_threat_determinism():
    kwargs = {
        "ts": TS, "hostname": HOSTNAME, "serial": SERIAL,
        "src_ip": "203.0.113.5", "dst_ip": "10.10.5.11",
        "src_port": 44321, "dst_port": 443, "proto": "tcp",
    }
    assert panw.panos_threat(**kwargs) == panw.panos_threat(**kwargs)


# ---------------------------------------------------------------------------
# Timestamp format tests
# ---------------------------------------------------------------------------

def test_rfc3164_timestamp_in_header():
    msg = panw.panos_traffic(TS, HOSTNAME, SERIAL,
                             "10.10.5.11", "10.20.0.1",
                             45678, 4500, "udp",
                             100_000, 60_000, 40_000)
    # Header: <14>Aug 11 12:34:56 palo-fw-prod ...
    # day=11 is space-padded to "11" (two chars)
    assert re.search(r"<14>Aug 11 12:34:56 ", msg), (
        f"RFC3164 timestamp not found in header: {msg[:60]!r}"
    )


def test_rfc3164_timestamp_single_digit_day():
    ts_single = datetime(2026, 8, 1, 0, 0, 0, tzinfo=UTC)
    msg = panw.panos_traffic(ts_single, HOSTNAME, SERIAL,
                             "10.10.5.11", "10.20.0.1",
                             45678, 4500, "udp",
                             100_000, 60_000, 40_000)
    # Day 1 should be space-padded: "Aug  1"
    assert re.search(r"<14>Aug  1 00:00:00 ", msg), (
        f"RFC3164 single-digit day not space-padded: {msg[:60]!r}"
    )


def test_panos_timestamp_format_in_csv():
    msg = panw.panos_traffic(TS, HOSTNAME, SERIAL,
                             "10.10.5.11", "10.20.0.1",
                             45678, 4500, "udp",
                             100_000, 60_000, 40_000)
    assert "2026/08/11 12:34:56" in msg, (
        f"PAN-OS timestamp 2026/08/11 12:34:56 not found in: {msg[:120]!r}"
    )
