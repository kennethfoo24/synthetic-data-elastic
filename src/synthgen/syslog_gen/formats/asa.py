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


def asa_104001(ts: datetime, hostname: str, unit: str = "Primary") -> str:
    """ASA failover: this unit is switching to ACTIVE (severity 1 = alert).

    Example::

        %ASA-1-104001: (Secondary) Switching to ACTIVE - Loss of communication
        with mate on interface failover-link
    """
    body = (
        f"({unit}) Switching to ACTIVE - Loss of communication "
        "with mate on interface failover-link"
    )
    return _line(ts, hostname, 1, "104001", body)


def asa_104002(ts: datetime, hostname: str, unit: str = "Primary") -> str:
    """ASA failover: this unit is switching to STANDBY (severity 1 = alert).

    Example::

        %ASA-1-104002: (Primary) Switching to STANDBY - Other side is ACTIVE
    """
    body = f"({unit}) Switching to STANDBY - Other side is ACTIVE"
    return _line(ts, hostname, 1, "104002", body)
