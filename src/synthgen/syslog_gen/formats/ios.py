from __future__ import annotations

from datetime import datetime

_FACILITY = 23  # local7, IOS default


def ios_timestamp(ts: datetime) -> str:
    """Format: Aug 11 2026 12:34:56.789 (day not zero-padded, millis)."""
    ms = ts.microsecond // 1000
    return f"{ts.strftime('%b')} {ts.day} {ts.strftime('%Y %H:%M:%S')}.{ms:03d}"


def _line(
    ts: datetime,
    hostname: str,
    seq: int,
    facility: str,
    severity: int,
    mnemonic: str,
    body: str,
) -> str:
    pri = _FACILITY * 8 + severity
    return f"<{pri}>{seq}: {hostname}: {ios_timestamp(ts)}: %{facility}-{severity}-{mnemonic}: {body}"


def ios_config_i(
    ts: datetime,
    hostname: str,
    seq: int,
    user: str = "admin",
    console: str = "console 0",
) -> str:
    body = f"Configured from console by {user} on {console}"
    return _line(ts, hostname, seq, "SYS", 5, "CONFIG_I", body)


def ios_link_updown(
    ts: datetime,
    hostname: str,
    seq: int,
    state: str,
    interface: str,
) -> str:
    body = f"Interface {interface}, changed state to {state}"
    return _line(ts, hostname, seq, "LINK", 3, "UPDOWN", body)


def ios_lineproto_updown(
    ts: datetime,
    hostname: str,
    seq: int,
    state: str,
    interface: str,
) -> str:
    body = f"Line protocol on Interface {interface}, changed state to {state}"
    return _line(ts, hostname, seq, "LINEPROTO", 5, "UPDOWN", body)


def ios_login_success(
    ts: datetime,
    hostname: str,
    seq: int,
    user: str,
    src_ip: str,
) -> str:
    body = (
        f"Login Success [user: {user}] [Source: {src_ip}] [localport: 22] "
        f"at {ios_timestamp(ts)}"
    )
    return _line(ts, hostname, seq, "SEC_LOGIN", 5, "LOGIN_SUCCESS", body)


def ios_logginghost(
    ts: datetime,
    hostname: str,
    seq: int,
    host: str = "10.10.0.100",
) -> str:
    body = f"Logging to host {host} port 514 started - CLI initiated"
    return _line(ts, hostname, seq, "SYS", 6, "LOGGINGHOST_STARTSTOP", body)


def ios_stp_topology_change(
    ts: datetime,
    hostname: str,
    seq: int,
    vlan: int,
    interface: str,
) -> str:
    """STP topology change notification.

    Example::

        %SPANTREE-2-TOPOLOGY_CHANGE: VLAN0001 [port GigabitEthernet0/1] topology changed
    """
    body = f"VLAN{vlan:04d} [port {interface}] topology changed"
    return _line(ts, hostname, seq, "SPANTREE", 2, "TOPOLOGY_CHANGE", body)


def ios_stp_portstatus(
    ts: datetime,
    hostname: str,
    seq: int,
    interface: str,
    state: str,
) -> str:
    """STP port state change.

    Example::

        %SPANTREE-7-PORTSTATUS: GigabitEthernet0/1 moved to Listening
    """
    body = f"{interface} moved to {state}"
    return _line(ts, hostname, seq, "SPANTREE", 7, "PORTSTATUS", body)


def ios_cpu_threshold(
    ts: datetime,
    hostname: str,
    seq: int,
    process: str = "IP Input",
    cpu_pct: int = 90,
) -> str:
    """CPU hog / threshold exceeded (SYS-3-CPUHOG).

    Example::

        %SYS-3-CPUHOG: Task is running for 2 seconds or more,
        Process = IP Input, CPU utilization 90%
    """
    body = (
        f"Task is running for 2 seconds or more, "
        f"Process = {process}, CPU utilization {cpu_pct}%"
    )
    return _line(ts, hostname, seq, "SYS", 3, "CPUHOG", body)
