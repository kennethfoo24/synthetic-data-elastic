"""Cisco Meraki webhook event sender.

Posts synthetic Meraki-shaped webhook payloads to an ``http_endpoint`` listener
(the ``cisco_meraki`` Elastic integration, stream ``cisco_meraki.events``).

Invoked as::

    synthgen meraki-webhook --target-host=HOST --target-port=PORT [--seed N]

The target URL is constructed as ``http://{host}:{port}/meraki/events``.

Environment
-----------
``MERAKI_WEBHOOK_SECRET``
    Shared secret included in every payload as ``sharedSecret``.
    Default: ``synthetic-meraki-secret``.
"""
from __future__ import annotations

import random
import sys
import time
from datetime import UTC, datetime

import httpx

DEFAULT_SECRET = "synthetic-meraki-secret"

_ALERT_TYPES = [
    "APs went down",
    "APs came up",
    "Clients connected",
    "Network usage alert",
    "Rogue AP detected",
]

# Fixed device metadata — all values deterministic, not rng-dependent.
_AP_SERIALS: dict[str, str] = {
    "meraki-ap-01": "Q2KD-XXX1-AAAA",
    "meraki-ap-02": "Q2KD-XXX2-BBBB",
}

_DEVICE_MACS: dict[str, str] = {
    "meraki-ap-01": "aa:bb:cc:dd:ee:01",
    "meraki-ap-02": "aa:bb:cc:dd:ee:02",
}

_DEVICE_MODELS: dict[str, str] = {
    "meraki-ap-01": "MR46",
    "meraki-ap-02": "MR46",
}

_ORG_NAME = "synthetic-org"
_ORG_URL = "https://dashboard.meraki.com/o/1/manage/organization/overview"
_NETWORK_URL = "https://n1.meraki.com/production-wifi/n/N_1/manage/usage/list"


def _alert_type_id(alert_type: str) -> str:
    """Derive a snake_case alertTypeId from the human-readable alertType."""
    return alert_type.lower().replace(" ", "_")


def _device_url(device_name: str) -> str:
    serial_slug = _AP_SERIALS[device_name].replace("-", "")
    return (
        f"https://n1.meraki.com/production-wifi/n/{serial_slug}"
        "/manage/nodes/new_list/000000000000"
    )


def build_events(t: datetime, rng: random.Random, secret: str, n: int) -> list[dict]:
    """Build ``n`` synthetic Meraki webhook event payloads.

    This is a pure builder — no I/O.  All values are deterministic from
    ``(t, rng, secret)``; no wall-clock reads occur inside this function.

    The payload schema matches what the cisco_meraki Elastic integration's
    ingest pipeline expects for the ``cisco_meraki.events`` data stream.
    Required fields verified against live pipeline output:
        deviceMac, deviceModel, deviceUrl, deviceTags, networkUrl,
        alertId, alertLevel, alertTypeId, organizationName, organizationUrl,
        alertData (plus the original version/sharedSecret/sentAt/… set).
    """
    sent_at = t.strftime("%Y-%m-%dT%H:%M:%SZ")
    events: list[dict] = []
    for _ in range(n):
        device_name = rng.choice(list(_AP_SERIALS.keys()))
        serial = _AP_SERIALS[device_name]
        alert_type = rng.choice(_ALERT_TYPES)
        alert_id = f"alert-{rng.randint(100_000, 999_999)}"
        events.append({
            # Core identity
            "version": "0.1",
            "sharedSecret": secret,
            # Timing (all derived from t — no wall-clock inside build_events)
            "sentAt": sent_at,
            "occurredAt": sent_at,
            # Organisation
            "organizationId": "1",
            "organizationName": _ORG_NAME,
            "organizationUrl": _ORG_URL,
            # Network
            "networkId": "N_1",
            "networkName": "production-wifi",
            "networkUrl": _NETWORK_URL,
            # Device
            "deviceSerial": serial,
            "deviceName": device_name,
            "deviceMac": _DEVICE_MACS[device_name],
            "deviceModel": _DEVICE_MODELS[device_name],
            "deviceUrl": _device_url(device_name),
            "deviceTags": [],
            # Alert
            "alertId": alert_id,
            "alertType": alert_type,
            "alertTypeId": _alert_type_id(alert_type),
            "alertLevel": "informational",
            "alertData": {},
        })
    return events


def _post_with_retry(
    client: httpx.Client,
    url: str,
    payload: dict,
    max_retries: int = 3,
) -> None:
    """POST a single event with exponential back-off; logs but never raises."""
    delay = 1.0
    for attempt in range(max_retries):
        try:
            r = client.post(url, json=payload, timeout=10)
            if r.status_code < 500:
                if r.status_code >= 300:
                    print(f"webhook rejected: HTTP {r.status_code}", file=sys.stderr, flush=True)
                return  # 2xx/3xx/4xx — not a transient server error
            print(
                f"meraki-webhook: HTTP {r.status_code} on attempt {attempt + 1}",
                flush=True,
            )
        except httpx.RequestError as exc:
            print(
                f"meraki-webhook: request error on attempt {attempt + 1}: {exc}",
                flush=True,
            )
        time.sleep(delay)
        delay *= 2.0
    print(f"meraki-webhook: gave up posting after {max_retries} attempts", flush=True)


def run(target_url: str, secret: str = DEFAULT_SECRET, seed: int = 0) -> None:
    """Main send loop: POST 1-3 events every ~30 seconds, never crash-loop.

    Parameters
    ----------
    target_url:
        Full URL of the ``http_endpoint`` listener,
        e.g. ``http://elastic-agent:9004/meraki/events``.
    secret:
        Shared secret written into each payload's ``sharedSecret`` field.
    seed:
        RNG seed for deterministic replay.
    """
    rng = random.Random(seed)
    client = httpx.Client()
    print(f"meraki-webhook: -> {target_url}", flush=True)
    try:
        while True:
            t = datetime.now(UTC)
            n = rng.randint(1, 3)
            events = build_events(t, rng, secret, n)
            for event in events:
                _post_with_retry(client, target_url, event)
            time.sleep(30)
    finally:
        client.close()
