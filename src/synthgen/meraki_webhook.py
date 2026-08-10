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

_AP_SERIALS: dict[str, str] = {
    "meraki-ap-01": "Q2KD-XXX1-AAAA",
    "meraki-ap-02": "Q2KD-XXX2-BBBB",
}


def build_events(t: datetime, rng: random.Random, secret: str, n: int) -> list[dict]:
    """Build ``n`` synthetic Meraki webhook event payloads.

    This is a pure builder — no I/O.  Each call with the same ``rng`` state
    and ``t`` is deterministic, making it straightforwardly unit-testable.
    """
    sent_at = t.strftime("%Y-%m-%dT%H:%M:%SZ")
    events: list[dict] = []
    for _ in range(n):
        device_name = rng.choice(list(_AP_SERIALS.keys()))
        serial = _AP_SERIALS[device_name]
        alert_type = rng.choice(_ALERT_TYPES)
        events.append({
            "version": "0.1",
            "sharedSecret": secret,
            "sentAt": sent_at,
            "organizationId": "1",
            "networkId": "N_1",
            "networkName": "production-wifi",
            "deviceSerial": serial,
            "deviceName": device_name,
            "alertType": alert_type,
            "occurredAt": sent_at,
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
