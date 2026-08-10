"""NetFlow v9 packet encoder (RFC 3954).

Only the fields required by the Elastic netflow integration are implemented:
  IPV4_SRC_ADDR, IPV4_DST_ADDR, L4_SRC_PORT, L4_DST_PORT, PROTOCOL,
  IN_BYTES, IN_PKTS, FIRST_SWITCHED, LAST_SWITCHED.

All multi-byte values are big-endian per the spec.
"""

from __future__ import annotations

import socket
import struct
from dataclasses import dataclass

NETFLOW_VERSION = 9
TEMPLATE_ID = 256  # first available user template ID
SOURCE_ID = 1      # exporter ID (one exporter = the generator pod)

# Field definitions: (field_type, field_length) per RFC 3954 / IANA IPFIX registry
_FIELDS: list[tuple[int, int]] = [
    (8, 4),   # IPV4_SRC_ADDR
    (12, 4),  # IPV4_DST_ADDR
    (7, 2),   # L4_SRC_PORT
    (11, 2),  # L4_DST_PORT
    (4, 1),   # PROTOCOL
    (1, 4),   # IN_BYTES
    (2, 4),   # IN_PKTS
    (22, 4),  # FIRST_SWITCHED (sysUptime ms when first packet observed)
    (21, 4),  # LAST_SWITCHED  (sysUptime ms when last packet observed)
]

# Fixed sizes (used by the main loop for MTU chunking)
RECORD_SIZE: int = sum(flen for _, flen in _FIELDS)  # 29 bytes per data record
HEADER_SIZE: int = 20     # NetFlow v9 packet header
DATA_FS_HEADER_SIZE: int = 4  # data flowset header (flowset_id + length)

# Template flowset is fixed and pre-computed:
#   4B flowset header (id=0, length)
#   4B template record header (template_id, field_count)
#   9 × 4B field definitions
# Total = 44 bytes; 44 % 4 == 0, no padding required.
_TEMPLATE_FLOWSET: bytes = (
    struct.pack(">HH", 0, 4 + 4 + len(_FIELDS) * 4)   # flowset_id=0, total length
    + struct.pack(">HH", TEMPLATE_ID, len(_FIELDS))     # template_id=256, field_count=9
    + b"".join(struct.pack(">HH", ft, fl) for ft, fl in _FIELDS)
)
TEMPLATE_FS_SIZE: int = len(_TEMPLATE_FLOWSET)  # 44


@dataclass
class FlowRecord:
    """One NetFlow v9 data record.

    Forward and reverse directions are emitted as separate records.
    """

    src_addr: str    # dotted-quad IPv4
    dst_addr: str    # dotted-quad IPv4
    src_port: int
    dst_port: int
    protocol: int    # 6 = TCP, 17 = UDP
    in_bytes: int
    in_pkts: int
    first_switched: int  # sysUptime ms when first packet of flow was observed
    last_switched: int   # sysUptime ms when last packet of flow was observed


def _pack_record(rec: FlowRecord) -> bytes:
    return (
        socket.inet_aton(rec.src_addr)
        + socket.inet_aton(rec.dst_addr)
        + struct.pack(">HH", rec.src_port, rec.dst_port)
        + struct.pack(">B", rec.protocol)
        + struct.pack(">II", rec.in_bytes, rec.in_pkts)
        + struct.pack(">II", rec.first_switched, rec.last_switched)
    )


def _pack_data_flowset(records: list[FlowRecord]) -> bytes:
    payload = b"".join(_pack_record(r) for r in records)
    raw_len = DATA_FS_HEADER_SIZE + len(payload)
    pad_len = (-raw_len) % 4  # pad to 4-byte boundary
    return (
        struct.pack(">HH", TEMPLATE_ID, raw_len + pad_len)
        + payload
        + bytes(pad_len)
    )


def build_packet(
    records: list[FlowRecord],
    sys_uptime_ms: int,
    unix_secs: int,
    sequence: int,
    include_template: bool,
) -> bytes:
    """Build a NetFlow v9 UDP export packet.

    count (RFC 3954): template flowset counts as 1; each data record counts as 1.
    All uint32 fields are masked to 32 bits — callers may pass raw timestamp values.
    """
    flowsets: list[bytes] = []
    if include_template:
        flowsets.append(_TEMPLATE_FLOWSET)
    flowsets.append(_pack_data_flowset(records))

    count = len(records) + (1 if include_template else 0)
    header = struct.pack(
        ">HHIIII",
        NETFLOW_VERSION,
        count,
        sys_uptime_ms & 0xFFFFFFFF,
        unix_secs & 0xFFFFFFFF,
        sequence & 0xFFFFFFFF,
        SOURCE_ID,
    )
    return header + b"".join(flowsets)
