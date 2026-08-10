"""Round-trip tests for the NetFlow v9 encoder.

Every test decodes its own bytes with struct.unpack and asserts the field
values — this proves the wire format is correct end-to-end.
"""

from __future__ import annotations

import socket
import struct

from synthgen.netflow_gen.encoder import (
    DATA_FS_HEADER_SIZE,
    HEADER_SIZE,
    NETFLOW_VERSION,
    RECORD_SIZE,
    SOURCE_ID,
    TEMPLATE_FS_SIZE,
    TEMPLATE_ID,
    FlowRecord,
    build_packet,
)


def _rec(
    src="10.0.0.1",
    dst="10.0.0.2",
    sp=1234,
    dp=443,
    proto=6,
    in_bytes=1000,
    in_pkts=2,
    first=100,
    last=900,
) -> FlowRecord:
    return FlowRecord(
        src_addr=src,
        dst_addr=dst,
        src_port=sp,
        dst_port=dp,
        protocol=proto,
        in_bytes=in_bytes,
        in_pkts=in_pkts,
        first_switched=first,
        last_switched=last,
    )


# ---------------------------------------------------------------------------
# Header
# ---------------------------------------------------------------------------

def test_header_fields_round_trip():
    pkt = build_packet([_rec()], sys_uptime_ms=12345, unix_secs=1_700_000_000,
                       sequence=42, include_template=True)
    version, _count, uptime, unix, seq, src_id = struct.unpack(">HHIIII", pkt[:HEADER_SIZE])
    assert version == NETFLOW_VERSION
    assert uptime == 12345
    assert unix == 1_700_000_000
    assert seq == 42
    assert src_id == SOURCE_ID


def test_header_count_with_template():
    # RFC 3954: count = template records (1) + data records (N)
    pkt = build_packet([_rec(), _rec()], sys_uptime_ms=0, unix_secs=0,
                       sequence=0, include_template=True)
    _, count, *_ = struct.unpack(">HHIIII", pkt[:HEADER_SIZE])
    assert count == 3  # 1 template + 2 data records


def test_header_count_without_template():
    pkt = build_packet([_rec(), _rec(), _rec()], sys_uptime_ms=0, unix_secs=0,
                       sequence=0, include_template=False)
    _, count, *_ = struct.unpack(">HHIIII", pkt[:HEADER_SIZE])
    assert count == 3  # 3 data records, no template


def test_uint32_fields_are_masked():
    # Values larger than 2^32 must be masked, not cause struct errors.
    large = 2**33 + 7
    pkt = build_packet([_rec()], sys_uptime_ms=large, unix_secs=large,
                       sequence=large, include_template=False)
    _, _, uptime, unix, seq, _ = struct.unpack(">HHIIII", pkt[:HEADER_SIZE])
    assert uptime == large & 0xFFFFFFFF
    assert unix == large & 0xFFFFFFFF
    assert seq == large & 0xFFFFFFFF


# ---------------------------------------------------------------------------
# Template flowset layout
# ---------------------------------------------------------------------------

def test_template_flowset_id_is_zero():
    pkt = build_packet([_rec()], sys_uptime_ms=0, unix_secs=0, sequence=0,
                       include_template=True)
    fs_id, _fs_len = struct.unpack(">HH", pkt[HEADER_SIZE : HEADER_SIZE + 4])
    assert fs_id == 0


def test_template_flowset_total_size():
    # 4 (header) + 4 (tmpl_id + field_count) + 9×4 (fields) = 44; 44 % 4 == 0
    assert TEMPLATE_FS_SIZE == 44
    pkt = build_packet([_rec()], sys_uptime_ms=0, unix_secs=0, sequence=0,
                       include_template=True)
    _, fs_len = struct.unpack(">HH", pkt[HEADER_SIZE : HEADER_SIZE + 4])
    assert fs_len == TEMPLATE_FS_SIZE


def test_template_id_and_field_count():
    pkt = build_packet([_rec()], sys_uptime_ms=0, unix_secs=0, sequence=0,
                       include_template=True)
    pos = HEADER_SIZE + 4  # skip template flowset header
    tmpl_id, field_count = struct.unpack(">HH", pkt[pos : pos + 4])
    assert tmpl_id == TEMPLATE_ID
    assert field_count == 9


def test_template_field_definitions():
    """All nine field (type, length) pairs must match the RFC 3954 spec."""
    expected = [
        (8, 4),   # IPV4_SRC_ADDR
        (12, 4),  # IPV4_DST_ADDR
        (7, 2),   # L4_SRC_PORT
        (11, 2),  # L4_DST_PORT
        (4, 1),   # PROTOCOL
        (1, 4),   # IN_BYTES
        (2, 4),   # IN_PKTS
        (22, 4),  # FIRST_SWITCHED
        (21, 4),  # LAST_SWITCHED
    ]
    pkt = build_packet([_rec()], sys_uptime_ms=0, unix_secs=0, sequence=0,
                       include_template=True)
    pos = HEADER_SIZE + 4 + 4  # skip main header + FS header + tmpl_id/field_count
    for ftype, flen in expected:
        t, l = struct.unpack(">HH", pkt[pos : pos + 4])
        assert (t, l) == (ftype, flen), f"field ({ftype},{flen}) mismatch: got ({t},{l})"
        pos += 4


# ---------------------------------------------------------------------------
# Data flowset and record values
# ---------------------------------------------------------------------------

def test_data_flowset_id_equals_template_id():
    pkt = build_packet([_rec()], sys_uptime_ms=0, unix_secs=0, sequence=0,
                       include_template=True)
    data_pos = HEADER_SIZE + TEMPLATE_FS_SIZE
    fs_id, _ = struct.unpack(">HH", pkt[data_pos : data_pos + 4])
    assert fs_id == TEMPLATE_ID


def test_data_record_fields_round_trip():
    rec = _rec(src="192.168.1.10", dst="10.10.7.21", sp=54321, dp=5432,
               proto=6, in_bytes=48000, in_pkts=60, first=1000, last=1950)
    pkt = build_packet([rec], sys_uptime_ms=2000, unix_secs=0, sequence=0,
                       include_template=True)

    pos = HEADER_SIZE + TEMPLATE_FS_SIZE + DATA_FS_HEADER_SIZE
    src_ip = socket.inet_ntoa(pkt[pos : pos + 4]); pos += 4
    dst_ip = socket.inet_ntoa(pkt[pos : pos + 4]); pos += 4
    sp, dp = struct.unpack(">HH", pkt[pos : pos + 4]); pos += 4
    (proto,) = struct.unpack(">B", pkt[pos : pos + 1]); pos += 1
    in_bytes, in_pkts = struct.unpack(">II", pkt[pos : pos + 8]); pos += 8
    first, last = struct.unpack(">II", pkt[pos : pos + 8]); pos += 8

    assert src_ip == "192.168.1.10"
    assert dst_ip == "10.10.7.21"
    assert sp == 54321
    assert dp == 5432
    assert proto == 6
    assert in_bytes == 48000
    assert in_pkts == 60
    assert first == 1000
    assert last == 1950


def test_udp_protocol_value():
    rec = _rec(proto=17)
    pkt = build_packet([rec], sys_uptime_ms=0, unix_secs=0, sequence=0,
                       include_template=False)
    pos = HEADER_SIZE + DATA_FS_HEADER_SIZE + 4 + 4 + 2 + 2  # skip addrs + ports
    (proto,) = struct.unpack(">B", pkt[pos : pos + 1])
    assert proto == 17


# ---------------------------------------------------------------------------
# 4-byte alignment / padding
# ---------------------------------------------------------------------------

def test_data_flowset_length_is_4byte_aligned():
    # 1 record: 4 (header) + 29 (record) = 33 → padded to 36
    pkt = build_packet([_rec()], sys_uptime_ms=0, unix_secs=0, sequence=0,
                       include_template=False)
    _, fs_len = struct.unpack(">HH", pkt[HEADER_SIZE : HEADER_SIZE + 4])
    assert fs_len % 4 == 0
    assert fs_len == 36  # 4 + 29 + 3 padding


def test_one_record_padding_bytes_are_zero():
    pkt = build_packet([_rec()], sys_uptime_ms=0, unix_secs=0, sequence=0,
                       include_template=False)
    # data flowset: 4 header + 29 record + 3 pad = 36
    pad_start = HEADER_SIZE + 4 + RECORD_SIZE
    pad_bytes = pkt[pad_start : pad_start + 3]
    assert pad_bytes == b"\x00\x00\x00"


def test_two_records_length_is_4byte_aligned():
    # 2 records: 4 + 58 = 62 → padded to 64
    pkt = build_packet([_rec(), _rec()], sys_uptime_ms=0, unix_secs=0,
                       sequence=0, include_template=False)
    _, fs_len = struct.unpack(">HH", pkt[HEADER_SIZE : HEADER_SIZE + 4])
    assert fs_len % 4 == 0
    assert fs_len == 64  # 4 + 58 + 2 padding


def test_four_records_no_padding_needed():
    # 4 records: 4 + 116 = 120, which is already 4-byte aligned
    pkt = build_packet([_rec()] * 4, sys_uptime_ms=0, unix_secs=0,
                       sequence=0, include_template=False)
    _, fs_len = struct.unpack(">HH", pkt[HEADER_SIZE : HEADER_SIZE + 4])
    assert fs_len == 120


# ---------------------------------------------------------------------------
# MTU and size constants
# ---------------------------------------------------------------------------

def test_record_size_constant():
    assert RECORD_SIZE == 29  # 4+4+2+2+1+4+4+4+4


def test_28_records_fit_under_1400_bytes():
    # 14 topology flows × 2 (fwd + rev) = 28 records
    records = [_rec()] * 28
    pkt = build_packet(records, sys_uptime_ms=0, unix_secs=0, sequence=0,
                       include_template=True)
    assert len(pkt) < 1400


def test_no_template_packet_starts_with_data_flowset():
    pkt = build_packet([_rec()], sys_uptime_ms=0, unix_secs=0, sequence=0,
                       include_template=False)
    fs_id = struct.unpack(">H", pkt[HEADER_SIZE : HEADER_SIZE + 2])[0]
    assert fs_id == TEMPLATE_ID
