"""PAN-OS 10.x syslog message formatters (TRAFFIC and THREAT log types).

Each CSV record is built from an ordered list of ``(field_name, value)`` tuples
so the field count is transparent and straightforward to verify or fix when the
Elastic pipeline simulate gate is run.

TRAFFIC: 67 fields (PAN-OS 10.2 traffic log spec)
THREAT:  78 fields (PAN-OS 10.2 threat log spec)

Syslog header: ``<14>{rfc3164_ts} {hostname} {csv}``
  - PRI 14 = facility 1 (user) * 8 + severity 6 (informational)
  - rfc3164_ts: ``Aug 11 12:34:56`` (no year, space-padded day)
  - csv field[0] is the literal ``1`` (PAN-OS future_use placeholder)
"""
from __future__ import annotations

from datetime import datetime

_PRIORITY = 14  # facility=1 (user) * 8 + severity=6 (informational)


def _rfc3164_ts(ts: datetime) -> str:
    """RFC 3164 timestamp: ``Aug 11 12:34:56`` (no year, space-padded day)."""
    return f"{ts.strftime('%b')} {ts.day:2d} {ts.strftime('%H:%M:%S')}"


def _panos_ts(ts: datetime) -> str:
    """PAN-OS receive/generated time: ``2026/08/11 12:34:56``."""
    return ts.strftime("%Y/%m/%d %H:%M:%S")


def _csv(fields: list[tuple[str, object]]) -> str:
    return ",".join(str(v) for _, v in fields)


# ---------------------------------------------------------------------------
# TRAFFIC log (subtype=end) — 67 fields
# ---------------------------------------------------------------------------

def panos_traffic(
    ts: datetime,
    hostname: str,
    serial: str,
    src_ip: str,
    dst_ip: str,
    src_port: int,
    dst_port: int,
    proto: str,
    bytes_total: int,
    bytes_sent: int,
    bytes_received: int,
    *,
    src_zone: str = "inside",
    dst_zone: str = "outside",
    app: str = "web-browsing",
    rule: str = "allow-egress",
    session_id: int = 12345,
    elapsed: int = 30,
    seq_no: int = 1000,
) -> str:
    """Return a PAN-OS 10.2 TRAFFIC (subtype=end) syslog line (67 CSV fields)."""
    rx = _panos_ts(ts)
    gen = _panos_ts(ts)
    pkts_sent = max(1, bytes_sent // 1500)
    pkts_recv = max(1, bytes_received // 1500)
    packets = pkts_sent + pkts_recv

    # fmt: off
    fields: list[tuple[str, object]] = [
        # idx  name
        # 0
        ("future_use_1",         "1"),
        # 1
        ("receive_time",         rx),
        # 2
        ("serial",               serial),
        # 3
        ("type",                 "TRAFFIC"),
        # 4
        ("subtype",              "end"),
        # 5
        ("future_use_2",         ""),
        # 6
        ("generated_time",       gen),
        # 7
        ("src_ip",               src_ip),
        # 8
        ("dst_ip",               dst_ip),
        # 9
        ("nat_src_ip",           src_ip),
        # 10
        ("nat_dst_ip",           dst_ip),
        # 11
        ("rule",                 rule),
        # 12
        ("src_user",             ""),
        # 13
        ("dst_user",             ""),
        # 14
        ("app",                  app),
        # 15
        ("vsys",                 "vsys1"),
        # 16
        ("src_zone",             src_zone),
        # 17
        ("dst_zone",             dst_zone),
        # 18
        ("in_if",                "ethernet1/1"),
        # 19
        ("out_if",               "ethernet1/2"),
        # 20
        ("log_forwarding_profile", ""),
        # 21
        ("future_use_3",         ""),
        # 22
        ("session_id",           session_id),
        # 23
        ("repeat_count",         1),
        # 24
        ("src_port",             src_port),
        # 25
        ("dst_port",             dst_port),
        # 26
        ("nat_src_port",         src_port),
        # 27
        ("nat_dst_port",         dst_port),
        # 28
        ("flags",                "0x400000"),
        # 29
        ("proto",                proto),
        # 30
        ("action",               "allow"),
        # 31
        ("bytes",                bytes_total),
        # 32
        ("bytes_sent",           bytes_sent),
        # 33
        ("bytes_received",       bytes_received),
        # 34
        ("packets",              packets),
        # 35
        ("start_time",           rx),
        # 36
        ("elapsed",              elapsed),
        # 37
        ("category",             "any"),
        # 38
        ("future_use_4",         ""),
        # 39
        ("seq_no",               seq_no),
        # 40
        ("action_flags",         "0x0"),
        # 41
        ("src_location",         "10.0.0.0-10.255.255.255"),
        # 42
        ("dst_location",         "10.0.0.0-10.255.255.255"),
        # 43
        ("future_use_5",         ""),
        # 44
        ("pkts_sent",            pkts_sent),
        # 45
        ("pkts_received",        pkts_recv),
        # 46
        ("session_end_reason",   "aged-out"),
        # 47
        ("dg_hier_level_1",      ""),
        # 48
        ("dg_hier_level_2",      ""),
        # 49
        ("dg_hier_level_3",      ""),
        # 50
        ("dg_hier_level_4",      ""),
        # 51
        ("vsys_name",            ""),
        # 52
        ("device_name",          hostname),
        # 53
        ("action_source",        "from-policy"),
        # 54
        ("src_vm_uuid",          ""),
        # 55
        ("dst_vm_uuid",          ""),
        # 56
        ("tunnel_id",            ""),
        # 57
        ("monitor_tag",          ""),
        # 58
        ("parent_session_id",    ""),
        # 59
        ("parent_start_time",    ""),
        # 60
        ("tunnel_type",          "N/A"),
        # 61
        ("sctp_association_id",  ""),
        # 62
        ("sctp_chunks",          ""),
        # 63
        ("sctp_chunks_sent",     ""),
        # 64
        ("sctp_chunks_received", ""),
        # 65
        ("rule_uuid",            ""),
        # 66
        ("http2_connection",     ""),
    ]
    # fmt: on
    assert len(fields) == 67, f"BUG: TRAFFIC field count is {len(fields)}, expected 67"
    ts_str = _rfc3164_ts(ts)
    return f"<{_PRIORITY}>{ts_str} {hostname} {_csv(fields)}"


# ---------------------------------------------------------------------------
# THREAT log (subtype=vulnerability|spyware) — 78 fields
# ---------------------------------------------------------------------------

def panos_threat(
    ts: datetime,
    hostname: str,
    serial: str,
    src_ip: str,
    dst_ip: str,
    src_port: int,
    dst_port: int,
    proto: str,
    *,
    subtype: str = "vulnerability",
    threat_id: str = "36882",
    severity: str = "high",
    src_zone: str = "outside",
    dst_zone: str = "inside",
    app: str = "web-browsing",
    rule: str = "allow-egress",
    session_id: int = 99999,
    seq_no: int = 2000,
) -> str:
    """Return a PAN-OS 10.2 THREAT syslog line (78 CSV fields)."""
    rx = _panos_ts(ts)
    gen = _panos_ts(ts)

    # fmt: off
    fields: list[tuple[str, object]] = [
        # 0
        ("future_use_1",         "1"),
        # 1
        ("receive_time",         rx),
        # 2
        ("serial",               serial),
        # 3
        ("type",                 "THREAT"),
        # 4
        ("subtype",              subtype),
        # 5
        ("future_use_2",         ""),
        # 6
        ("generated_time",       gen),
        # 7
        ("src_ip",               src_ip),
        # 8
        ("dst_ip",               dst_ip),
        # 9
        ("nat_src_ip",           src_ip),
        # 10
        ("nat_dst_ip",           dst_ip),
        # 11
        ("rule",                 rule),
        # 12
        ("src_user",             ""),
        # 13
        ("dst_user",             ""),
        # 14
        ("app",                  app),
        # 15
        ("vsys",                 "vsys1"),
        # 16
        ("src_zone",             src_zone),
        # 17
        ("dst_zone",             dst_zone),
        # 18
        ("in_if",                "ethernet1/1"),
        # 19
        ("out_if",               "ethernet1/2"),
        # 20
        ("log_forwarding_profile", ""),
        # 21
        ("future_use_3",         ""),
        # 22
        ("session_id",           session_id),
        # 23
        ("repeat_count",         1),
        # 24
        ("src_port",             src_port),
        # 25
        ("dst_port",             dst_port),
        # 26
        ("nat_src_port",         src_port),
        # 27
        ("nat_dst_port",         dst_port),
        # 28
        ("flags",                "0x0"),
        # 29
        ("proto",                proto),
        # 30
        ("action",               "reset-both"),
        # 31
        ("misc",                 ""),
        # 32
        ("threat_id",            threat_id),
        # 33
        ("category",             "any"),
        # 34
        ("severity",             severity),
        # 35
        ("direction",            "client-to-server"),
        # 36
        ("seq_no",               seq_no),
        # 37
        ("action_flags",         "0x0"),
        # 38
        ("src_location",         "US"),
        # 39
        ("dst_location",         "10.0.0.0-10.255.255.255"),
        # 40
        ("future_use_4",         ""),
        # 41
        ("content_type",         ""),
        # 42
        ("pcap_id",              "0"),
        # 43
        ("file_digest",          ""),
        # 44
        ("cloud",                ""),
        # 45
        ("url_index",            ""),
        # 46
        ("user_agent",           ""),
        # 47
        ("file_type",            ""),
        # 48
        ("xff",                  ""),
        # 49
        ("referer",              ""),
        # 50
        ("sender",               ""),
        # 51
        ("subject",              ""),
        # 52
        ("recipient",            ""),
        # 53
        ("report_id",            ""),
        # 54
        ("dg_hier_level_1",      ""),
        # 55
        ("dg_hier_level_2",      ""),
        # 56
        ("dg_hier_level_3",      ""),
        # 57
        ("dg_hier_level_4",      ""),
        # 58
        ("vsys_name",            ""),
        # 59
        ("device_name",          hostname),
        # 60
        ("future_use_5",         ""),
        # 61
        ("src_vm_uuid",          ""),
        # 62
        ("dst_vm_uuid",          ""),
        # 63
        ("http_method",          ""),
        # 64
        ("tunnel_id",            ""),
        # 65
        ("monitor_tag",          ""),
        # 66
        ("parent_session_id",    ""),
        # 67
        ("parent_start_time",    ""),
        # 68
        ("tunnel_type",          "N/A"),
        # 69
        ("threat_category",      ""),
        # 70
        ("content_version",      ""),
        # 71
        ("future_use_6",         ""),
        # 72
        ("sctp_association_id",  ""),
        # 73
        ("payload_proto_id",     ""),
        # 74
        ("http_headers",         ""),
        # 75
        ("url_category_list",    ""),
        # 76
        ("rule_uuid",            ""),
        # 77
        ("http2_connection",     ""),
    ]
    # fmt: on
    assert len(fields) == 78, f"BUG: THREAT field count is {len(fields)}, expected 78"
    ts_str = _rfc3164_ts(ts)
    return f"<{_PRIORITY}>{ts_str} {hostname} {_csv(fields)}"


# ---------------------------------------------------------------------------
# SYSTEM log — 23 fields
# ---------------------------------------------------------------------------

def panos_system(
    ts: datetime,
    hostname: str,
    serial: str,
    *,
    subtype: str = "general",
    eventid: str = "general",
    severity: str = "informational",
    description: str = "System event logged",
    seq_no: int = 3000,
) -> str:
    """Return a PAN-OS 10.2 SYSTEM syslog line (23 CSV fields).

    Key positions (0-indexed from CSV start):
      [3] type="SYSTEM"  [4] subtype  [7] vsys  [8] eventid
      [13] severity  [22] device_name
    """
    rx = _panos_ts(ts)
    gen = _panos_ts(ts)

    # fmt: off
    fields: list[tuple[str, object]] = [
        # 0
        ("future_use_1",   "1"),
        # 1
        ("receive_time",   rx),
        # 2
        ("serial",         serial),
        # 3
        ("type",           "SYSTEM"),
        # 4
        ("subtype",        subtype),
        # 5
        ("future_use_2",   ""),
        # 6
        ("generated_time", gen),
        # 7
        ("vsys",           "vsys1"),
        # 8
        ("eventid",        eventid),
        # 9
        ("object",         ""),
        # 10
        ("future_use_3",   ""),
        # 11
        ("future_use_4",   ""),
        # 12
        ("module",         ""),
        # 13
        ("severity",       severity),
        # 14
        ("description",    description),
        # 15
        ("seq_no",         seq_no),
        # 16
        ("action_flags",   "0x0"),
        # 17
        ("dg_hier_level_1", ""),
        # 18
        ("dg_hier_level_2", ""),
        # 19
        ("dg_hier_level_3", ""),
        # 20
        ("dg_hier_level_4", ""),
        # 21
        ("vsys_name",      ""),
        # 22
        ("device_name",    hostname),
    ]
    # fmt: on
    assert len(fields) == 23, f"BUG: SYSTEM field count is {len(fields)}, expected 23"
    ts_str = _rfc3164_ts(ts)
    return f"<{_PRIORITY}>{ts_str} {hostname} {_csv(fields)}"
