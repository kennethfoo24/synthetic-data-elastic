import re
from datetime import UTC, datetime

from synthgen.syslog_gen.formats import ios

# microsecond=789000 → millis=789
TS = datetime(2026, 8, 11, 12, 34, 56, 789000, tzinfo=UTC)


def test_timestamp_format():
    assert ios.ios_timestamp(TS) == "Aug 11 2026 12:34:56.789"


def test_timestamp_day_not_zero_padded():
    ts_single = datetime(2026, 8, 1, 0, 0, 0, tzinfo=UTC)
    result = ios.ios_timestamp(ts_single)
    assert result.startswith("Aug 1 2026"), f"expected 'Aug 1 …', got '{result}'"


def test_config_i_exact():
    m = ios.ios_config_i(TS, "cisco-rtr-core-01", 12345, "admin1", "console 0")
    assert m == (
        "<189>12345: cisco-rtr-core-01: Aug 11 2026 12:34:56.789: "
        "%SYS-5-CONFIG_I: Configured from console by admin1 on console 0"
    )


def test_link_updown():
    m = ios.ios_link_updown(TS, "cisco-rtr-core-01", 100, "down", "GigabitEthernet0/1")
    assert m.startswith("<187>")  # severity 3: 23*8+3=187
    assert "%LINK-3-UPDOWN:" in m
    assert "Interface GigabitEthernet0/1, changed state to down" in m


def test_lineproto_updown():
    m = ios.ios_lineproto_updown(TS, "cisco-rtr-core-01", 101, "up", "GigabitEthernet0/1")
    assert m.startswith("<189>")  # severity 5: 23*8+5=189
    assert "%LINEPROTO-5-UPDOWN:" in m
    assert "Line protocol on Interface GigabitEthernet0/1, changed state to up" in m


def test_login_success():
    m = ios.ios_login_success(TS, "cisco-rtr-core-01", 200, "admin1", "10.10.1.5")
    assert m.startswith("<189>")
    assert "%SEC_LOGIN-5-LOGIN_SUCCESS:" in m
    assert "user: admin1" in m
    assert "Source: 10.10.1.5" in m


def test_logginghost():
    m = ios.ios_logginghost(TS, "cisco-rtr-core-01", 300, "10.10.0.100")
    assert m.startswith("<190>")  # severity 6: 23*8+6=190
    assert "%SYS-6-LOGGINGHOST_STARTSTOP:" in m
    assert "10.10.0.100" in m
    assert "port 514" in m


def test_priority_encoding():
    # local7 facility (23): PRI = 23*8 + severity
    assert re.match(r"^<189>", ios.ios_config_i(TS, "h", 1))          # 184+5=189
    assert re.match(r"^<187>", ios.ios_link_updown(TS, "h", 1, "up", "Gi0/0"))  # 184+3=187
    assert re.match(r"^<189>", ios.ios_lineproto_updown(TS, "h", 1, "up", "Gi0/0"))  # 184+5=189
    assert re.match(r"^<189>", ios.ios_login_success(TS, "h", 1, "u", "1.2.3.4"))  # 184+5=189
    assert re.match(r"^<190>", ios.ios_logginghost(TS, "h", 1))        # 184+6=190


def test_seq_appears_in_line():
    m = ios.ios_config_i(TS, "myrouter", 9999, "admin")
    assert m.startswith("<189>9999: myrouter:")
