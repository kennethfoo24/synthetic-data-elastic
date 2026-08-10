"""Cisco Meraki syslog wire format builders.

Meraki devices emit RFC 5424-ish syslog with this structure:

    <134>1 {epoch.frac} {device-name} {msg-type} {body}

Priority 134 = facility 16 (local0) × 8 + severity 6 (informational).
Timestamp is Unix epoch seconds with a 9-digit fractional part, rendered
deterministically from the supplied ``datetime`` (microseconds zero-padded to
nanosecond width; no sub-microsecond randomisation).

Message types emitted:
  flows   — MX firewall allow/deny flow records
  urls    — MX HTTP URL logging records
  events  — MR access-point client association / disassociation events
"""
from __future__ import annotations

from datetime import datetime

_PRI = 134  # facility 16 (local0) × 8 + severity 6 (informational)


def _ts(ts: datetime) -> str:
    """Epoch seconds with 9-digit fractional (microseconds + 3 trailing zeros)."""
    epoch_sec = int(ts.timestamp())
    micro = ts.microsecond
    return f"{epoch_sec}.{micro:06d}000"


def _line(ts: datetime, hostname: str, msg_type: str, body: str) -> str:
    return f"<{_PRI}>1 {_ts(ts)} {hostname} {msg_type} {body}"


def meraki_flow(
    ts: datetime,
    hostname: str,
    src_ip: str,
    src_port: int,
    dst_ip: str,
    dst_port: int,
    protocol: str = "tcp",
    pattern: str = "allow all",
) -> str:
    """MX firewall flow log line.

    Example::

        <134>1 1754912345.000000000 meraki-mx-01 flows src=10.10.3.11 \
dst=10.10.5.11 protocol=tcp sport=51234 dport=443 pattern: allow all
    """
    body = (
        f"src={src_ip} dst={dst_ip} protocol={protocol} "
        f"sport={src_port} dport={dst_port} pattern: {pattern}"
    )
    return _line(ts, hostname, "flows", body)


def meraki_url(
    ts: datetime,
    hostname: str,
    src_ip: str,
    src_port: int,
    dst_ip: str,
    dst_port: int,
    mac: str,
    method: str,
    url: str,
) -> str:
    """MX URL logging line.

    Example::

        <134>1 1754912345.000000000 meraki-mx-01 urls src=10.10.3.11:51234 \
dst=10.10.5.11:443 mac=AA:BB:CC:DD:EE:01 request: GET https://example.com/
    """
    body = (
        f"src={src_ip}:{src_port} dst={dst_ip}:{dst_port} "
        f"mac={mac} request: {method} {url}"
    )
    return _line(ts, hostname, "urls", body)


def meraki_event_association(
    ts: datetime,
    hostname: str,
    radio: int,
    vap: int,
    client_mac: str,
) -> str:
    """MR AP client association event.

    Example::

        <134>1 1754912345.000000000 meraki-ap-01 events \
type=association radio='0' vap='1' client_mac='AA:BB:CC:DD:EE:02'
    """
    body = f"type=association radio='{radio}' vap='{vap}' client_mac='{client_mac}'"
    return _line(ts, hostname, "events", body)


def meraki_event_disassociation(
    ts: datetime,
    hostname: str,
    radio: int,
    vap: int,
    client_mac: str,
    reason: int = 1,
) -> str:
    """MR AP client disassociation event.

    Example::

        <134>1 1754912345.000000000 meraki-ap-01 events \
type=disassociation radio='0' vap='1' client_mac='AA:BB:CC:DD:EE:02' reason=1
    """
    body = (
        f"type=disassociation radio='{radio}' vap='{vap}' "
        f"client_mac='{client_mac}' reason={reason}"
    )
    return _line(ts, hostname, "events", body)
