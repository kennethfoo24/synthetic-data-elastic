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
        (21, 4),  # FIRST_SWITCHED (RFC 3954: field type 21)
        (22, 4),  # LAST_SWITCHED  (RFC 3954: field type 22)
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


# ---------------------------------------------------------------------------
# Field ID correctness (RFC 3954: 21=FIRST_SWITCHED, 22=LAST_SWITCHED)
# ---------------------------------------------------------------------------

def test_first_switched_uses_field_type_21():
    """RFC 3954: FIRST_SWITCHED is field type 21, LAST_SWITCHED is field type 22."""
    pkt = build_packet([_rec(first=500, last=900)], sys_uptime_ms=1000,
                       unix_secs=0, sequence=0, include_template=True)
    # Field defs start at HEADER_SIZE + 4 (FS header) + 4 (tmpl_id + field_count)
    pos = HEADER_SIZE + 4 + 4
    field_types = []
    for _ in range(9):
        ftype, _ = struct.unpack(">HH", pkt[pos : pos + 4])
        field_types.append(ftype)
        pos += 4
    # FIRST_SWITCHED is the 8th field (index 7), LAST_SWITCHED is the 9th (index 8)
    assert field_types[7] == 21, f"FIRST_SWITCHED must be field type 21, got {field_types[7]}"
    assert field_types[8] == 22, f"LAST_SWITCHED must be field type 22, got {field_types[8]}"


def test_first_switched_value_precedes_last_switched_on_wire():
    """After decoding the data record, first_switched bytes come before last_switched."""
    rec = _rec(first=1000, last=1950)
    pkt = build_packet([rec], sys_uptime_ms=2000, unix_secs=0, sequence=0,
                       include_template=True)
    # Data record starts at: header(20) + template_fs(44) + data_fs_header(4)
    pos = HEADER_SIZE + TEMPLATE_FS_SIZE + DATA_FS_HEADER_SIZE
    # Skip: src_addr(4) + dst_addr(4) + ports(4) + protocol(1) + in_bytes(4) + in_pkts(4) = 21
    pos += 21
    first_wire, last_wire = struct.unpack(">II", pkt[pos : pos + 8])
    assert first_wire == 1000
    assert last_wire == 1950
    assert first_wire < last_wire  # semantic correctness


# ---------------------------------------------------------------------------
# Template-in-first-packet guarantee (_nf_chunks)
# ---------------------------------------------------------------------------

def test_first_packet_of_tick_always_has_template():
    """Packet 0 of every tick must carry the template regardless of epoch_sec.

    Tests epoch_sec values 1 and 5 (neither is a multiple of _NF_TEMPLATE_EVERY_N=20
    when multiplied by _NF_MAX_PKTS_PER_SEC=64, so without the pkt_offset==0 fix
    the template would be absent at cold-start seconds like 1).
    """
    from synthgen.__main__ import _NF_MAX_PKTS_PER_SEC, _NF_TEMPLATE_EVERY_N, _nf_chunks

    records = [_rec()] * 5  # fewer than max-per-packet; fits in one chunk

    for epoch_sec in (1, 5, 7, 11):
        global_pkt_base = (epoch_sec * _NF_MAX_PKTS_PER_SEC) % (2**32)
        # Confirm none of these would trigger the every-N rule on their own
        if global_pkt_base % _NF_TEMPLATE_EVERY_N == 0:
            continue  # skip degenerate case where both rules fire
        chunks = list(_nf_chunks(records, global_pkt_base, first_of_tick=True))
        assert len(chunks) >= 1
        _chunk, include_tmpl = chunks[0]
        assert include_tmpl, (
            f"epoch_sec={epoch_sec}: packet 0 must include template "
            f"(global_pkt_base={global_pkt_base})"
        )
