import re
from datetime import UTC, datetime

from synthgen.syslog_gen.formats import asa

TS = datetime(2026, 8, 10, 12, 34, 56, tzinfo=UTC)

def test_timestamp_format():
    assert asa.asa_timestamp(TS) == "Aug 10 2026 12:34:56"

def test_302013_built_connection():
    m = asa.asa_302013(TS, "cisco-asa-dr", 12345, "198.51.100.10", 54321, "10.20.5.11", 443)
    assert m == (
        "<166>Aug 10 2026 12:34:56 cisco-asa-dr : %ASA-6-302013: "
        "Built inbound TCP connection 12345 for outside:198.51.100.10/54321 "
        "(198.51.100.10/54321) to inside:10.20.5.11/443 (10.20.5.11/443)"
    )

def test_302014_teardown():
    m = asa.asa_302014(TS, "cisco-asa-dr", 12345, "198.51.100.10", 54321, "10.20.5.11", 443,
                       duration="0:01:02", byte_count=8412)
    assert "%ASA-6-302014: Teardown TCP connection 12345" in m
    assert "duration 0:01:02 bytes 8412" in m
    assert m.startswith("<166>")

def test_106023_deny():
    m = asa.asa_106023(TS, "cisco-asa-dr", "203.0.113.7", 41000, "10.20.5.11", 22)
    assert m.startswith("<164>")  # severity 4
    assert '%ASA-4-106023: Deny tcp src outside:203.0.113.7/41000 dst inside:10.20.5.11/22' in m
    assert 'by access-group "OUTSIDE_IN"' in m

def test_113005_auth_rejected():
    m = asa.asa_113005(TS, "cisco-asa-dr", "jsmith", "203.0.113.7")
    assert "%ASA-6-113005: AAA user authentication Rejected" in m
    assert "user = jsmith" in m and "user IP = 203.0.113.7" in m

def test_priority_encoding():
    # local4 facility (20): PRI = 20*8 + severity
    assert re.match(r"^<166>", asa.asa_302013(TS, "h", 1, "1.1.1.1", 1, "2.2.2.2", 2))
    assert re.match(r"^<164>", asa.asa_106023(TS, "h", "1.1.1.1", 1, "2.2.2.2", 2))
