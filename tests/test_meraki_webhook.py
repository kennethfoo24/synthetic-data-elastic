"""Unit tests for meraki_webhook — pure event builder + HTTP sender."""
from __future__ import annotations

import random
from datetime import UTC, datetime

import respx

from synthgen.meraki_webhook import (
    DEFAULT_SECRET,
    _post_with_retry,
    build_events,
)

_TS = datetime(2026, 8, 11, 12, 0, 0, tzinfo=UTC)


# ---------------------------------------------------------------------------
# build_events: pure builder
# ---------------------------------------------------------------------------

def test_build_events_count():
    rng = random.Random(42)
    events = build_events(_TS, rng, DEFAULT_SECRET, 3)
    assert len(events) == 3


_REQUIRED_FIELDS = (
    # Core identity
    "version", "sharedSecret",
    # Timing
    "sentAt", "occurredAt",
    # Organisation
    "organizationId", "organizationName", "organizationUrl",
    # Network
    "networkId", "networkName", "networkUrl",
    # Device — full set required by the ingest pipeline
    "deviceSerial", "deviceName", "deviceMac", "deviceModel",
    "deviceUrl", "deviceTags",
    # Alert
    "alertId", "alertType", "alertTypeId", "alertLevel", "alertData",
)


def test_build_events_schema_fields_present():
    rng = random.Random(0)
    events = build_events(_TS, rng, DEFAULT_SECRET, 3)
    for i, event in enumerate(events):
        for field in _REQUIRED_FIELDS:
            assert field in event, f"event[{i}] missing field: {field}"


def test_build_events_device_mac_format():
    rng = random.Random(0)
    events = build_events(_TS, rng, DEFAULT_SECRET, 10)
    for e in events:
        mac = e["deviceMac"]
        assert len(mac.split(":")) == 6, f"bad MAC format: {mac}"


def test_build_events_device_mac_matches_device():
    expected = {"meraki-ap-01": "aa:bb:cc:dd:ee:01", "meraki-ap-02": "aa:bb:cc:dd:ee:02"}
    rng = random.Random(0)
    events = build_events(_TS, rng, DEFAULT_SECRET, 20)
    for e in events:
        assert e["deviceMac"] == expected[e["deviceName"]]


def test_build_events_alert_type_id_derived():
    rng = random.Random(0)
    events = build_events(_TS, rng, DEFAULT_SECRET, 10)
    for e in events:
        # alertTypeId must be lowercase with spaces replaced by underscores
        expected_id = e["alertType"].lower().replace(" ", "_")
        assert e["alertTypeId"] == expected_id


def test_build_events_alert_level_is_informational():
    rng = random.Random(0)
    events = build_events(_TS, rng, DEFAULT_SECRET, 5)
    for e in events:
        assert e["alertLevel"] == "informational"


def test_build_events_device_tags_is_list():
    rng = random.Random(0)
    events = build_events(_TS, rng, DEFAULT_SECRET, 3)
    for e in events:
        assert isinstance(e["deviceTags"], list)


def test_build_events_alert_data_is_dict():
    rng = random.Random(0)
    events = build_events(_TS, rng, DEFAULT_SECRET, 3)
    for e in events:
        assert isinstance(e["alertData"], dict)


def test_build_events_version():
    rng = random.Random(0)
    event = build_events(_TS, rng, DEFAULT_SECRET, 1)[0]
    assert event["version"] == "0.1"


def test_build_events_shared_secret():
    rng = random.Random(0)
    secret = "my-test-secret"
    event = build_events(_TS, rng, secret, 1)[0]
    assert event["sharedSecret"] == secret


def test_build_events_sent_at_format():
    rng = random.Random(0)
    event = build_events(_TS, rng, DEFAULT_SECRET, 1)[0]
    # Must be ISO 8601 UTC string ending in Z
    assert event["sentAt"] == "2026-08-11T12:00:00Z"
    assert event["occurredAt"] == "2026-08-11T12:00:00Z"


def test_build_events_known_device_names():
    rng = random.Random(0)
    events = build_events(_TS, rng, DEFAULT_SECRET, 10)
    for e in events:
        assert e["deviceName"] in ("meraki-ap-01", "meraki-ap-02")


def test_build_events_serial_matches_device():
    serials = {"meraki-ap-01": "Q2KD-XXX1-AAAA", "meraki-ap-02": "Q2KD-XXX2-BBBB"}
    rng = random.Random(0)
    events = build_events(_TS, rng, DEFAULT_SECRET, 20)
    for e in events:
        assert e["deviceSerial"] == serials[e["deviceName"]]


def test_build_events_is_deterministic():
    rng1 = random.Random(7)
    rng2 = random.Random(7)
    e1 = build_events(_TS, rng1, DEFAULT_SECRET, 3)
    e2 = build_events(_TS, rng2, DEFAULT_SECRET, 3)
    assert e1 == e2


def test_build_events_network_fields():
    rng = random.Random(0)
    event = build_events(_TS, rng, DEFAULT_SECRET, 1)[0]
    assert event["organizationId"] == "1"
    assert event["networkId"] == "N_1"
    assert event["networkName"] == "production-wifi"


# ---------------------------------------------------------------------------
# _post_with_retry: HTTP sender
# ---------------------------------------------------------------------------

@respx.mock
def test_post_with_retry_success_on_first_attempt():
    import httpx
    respx.post("http://elastic-agent:9004/meraki/events").respond(status_code=200, json={})
    client = httpx.Client()
    # Should not raise
    _post_with_retry(client, "http://elastic-agent:9004/meraki/events", {"k": "v"}, max_retries=3)
    client.close()


@respx.mock
def test_post_with_retry_gives_up_after_max_retries(capsys):
    import httpx
    respx.post("http://elastic-agent:9004/meraki/events").respond(status_code=503, json={})
    client = httpx.Client()
    # Should complete without raising even after all retries fail
    _post_with_retry(client, "http://elastic-agent:9004/meraki/events", {"k": "v"}, max_retries=2)
    client.close()
    captured = capsys.readouterr()
    assert "gave up" in captured.out


@respx.mock
def test_post_with_retry_4xx_does_not_retry():
    """4xx (client error) must not trigger a retry — it returns immediately."""
    import httpx
    route = respx.post("http://elastic-agent:9004/meraki/events").respond(status_code=400, json={})
    client = httpx.Client()
    _post_with_retry(client, "http://elastic-agent:9004/meraki/events", {"k": "v"}, max_retries=3)
    client.close()
    # Only called once (no retry on 4xx)
    assert route.call_count == 1
