"""Pipeline simulate gate.

For each registered syslog source, generates representative sample lines and
verifies that the Elastic ingest pipeline parses them without errors via the
``_ingest/pipeline/{name}/_simulate`` API.

Usage:
    python -m synthsetup.simulate

Requires env vars: ES_URL, KIBANA_URL, ELASTIC_API_KEY
"""
from __future__ import annotations

import os
import sys
from collections.abc import Callable
from datetime import UTC, datetime

import httpx

from synthgen.syslog_gen.formats import asa, ios, panw
from synthsetup.fleet_client import FleetClient

_TS = datetime(2026, 8, 11, 12, 0, 0, tzinfo=UTC)

# Fixed device names matching the topology (used for sample log generation).
_ASA_HOST = "cisco-asa-dr"
_IOS_HOST = "cisco-rtr-core-01"
_PANW_HOST = "palo-fw-prod"
_PANW_SERIAL = "001901000001"


# ---------------------------------------------------------------------------
# Sample-line builders — one representative line per major message type
# ---------------------------------------------------------------------------

def _asa_samples() -> list[str]:
    """4 representative Cisco ASA syslog lines — one per emitted message type.

    Types covered: asa_302013, asa_302014, asa_106023, asa_113005
    """
    return [
        asa.asa_302013(_TS, _ASA_HOST, 123456, "203.0.113.1", 12345, "10.20.5.11", 443),
        asa.asa_302014(_TS, _ASA_HOST, 123456, "203.0.113.1", 12345, "10.20.5.11", 443,
                       duration="0:02:30", byte_count=512000),
        asa.asa_106023(_TS, _ASA_HOST, "203.0.113.2", 22222, "10.20.5.11", 22),
        asa.asa_113005(_TS, _ASA_HOST, "user5", "203.0.113.3"),
    ]


def _ios_samples() -> list[str]:
    """5 representative Cisco IOS syslog lines — one per emitted message type.

    Types covered: ios_login_success, ios_config_i, ios_link_updown,
                   ios_lineproto_updown, ios_logginghost
    """
    return [
        ios.ios_login_success(_TS, _IOS_HOST, 1001, "admin1", "10.10.1.5"),
        ios.ios_config_i(_TS, _IOS_HOST, 1002, "admin1"),
        ios.ios_link_updown(_TS, _IOS_HOST, 1003, "up", "GigabitEthernet0/1"),
        ios.ios_lineproto_updown(_TS, _IOS_HOST, 1004, "up", "GigabitEthernet0/1"),
        ios.ios_logginghost(_TS, _IOS_HOST, 1005, "10.10.0.100"),
    ]


def _panw_samples() -> list[str]:
    """2 representative PAN-OS syslog lines (TRAFFIC + THREAT)."""
    return [
        panw.panos_traffic(
            _TS, _PANW_HOST, _PANW_SERIAL,
            "10.10.5.11", "10.20.0.1", 45678, 4500, "udp",
            100_000, 60_000, 40_000,
            src_zone="inside", dst_zone="outside",
        ),
        panw.panos_threat(
            _TS, _PANW_HOST, _PANW_SERIAL,
            "203.0.113.5", "10.10.5.11", 44321, 443, "tcp",
            subtype="vulnerability",
        ),
    ]


# ---------------------------------------------------------------------------
# Registry: (package_name, dataset, sample_builder)
# Pipeline name = f"logs-{dataset}-{version}"  (version resolved at runtime)
# ---------------------------------------------------------------------------

REGISTRY: list[tuple[str, str, Callable[[], list[str]]]] = [
    ("cisco_asa", "cisco_asa.log", _asa_samples),
    ("cisco_ios", "cisco_ios.log", _ios_samples),
    ("panw",      "panw.panos",   _panw_samples),
]


# ---------------------------------------------------------------------------
# Core simulate logic
# ---------------------------------------------------------------------------

def run_simulate(es_url: str, kibana_url: str, api_key: str) -> list[str]:
    """Run the pipeline simulate gate for all registered sources.

    Returns a list of human-readable error strings.  An empty list means all
    pipelines accepted every sample document without errors.
    """
    fleet = FleetClient(kibana_url, api_key)
    es = httpx.Client(
        base_url=es_url.rstrip("/"),
        headers={"Authorization": f"ApiKey {api_key}"},
        timeout=30,
    )

    errors: list[str] = []

    for pkg, dataset, sample_fn in REGISTRY:
        # Resolve version at runtime from the installed package catalogue.
        try:
            version = fleet.latest_package_version(pkg)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{pkg}: failed to resolve package version: {exc}")
            continue

        pipeline = f"logs-{dataset}-{version}"
        lines = sample_fn()
        docs = [
            {"_index": f"logs-{dataset}-default", "_source": {"message": line}}
            for line in lines
        ]

        r = es.post(f"/_ingest/pipeline/{pipeline}/_simulate", json={"docs": docs})
        if r.status_code != 200:
            errors.append(
                f"{pkg}: simulate HTTP {r.status_code} (pipeline={pipeline}): "
                f"{r.text[:200]}"
            )
            continue

        result_docs = r.json().get("docs", [])

        if len(result_docs) != len(docs):
            errors.append(
                f"{pkg}: sent {len(docs)} docs but got {len(result_docs)} back "
                f"(pipeline={pipeline}) — possible drop processor"
            )

        for i, result in enumerate(result_docs):
            # Error surfaces at top-level OR inside "doc" depending on ES version.
            err = result.get("error") or result.get("doc", {}).get("error")
            if err:
                errors.append(
                    f"{pkg} doc[{i}]: {err.get('type', 'unknown')}: "
                    f"{err.get('reason', str(err))} (pipeline={pipeline})"
                )

    return errors


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    es_url = os.environ.get("ES_URL", "")
    kibana_url = os.environ.get("KIBANA_URL", "")
    api_key = os.environ.get("ELASTIC_API_KEY", "")
    if not (es_url and kibana_url and api_key):
        print("ERROR: ES_URL, KIBANA_URL, ELASTIC_API_KEY must be set", file=sys.stderr)
        sys.exit(1)

    print("==> pipeline simulate gate", flush=True)
    errors = run_simulate(es_url, kibana_url, api_key)
    if errors:
        for err in errors:
            print(f"  FAIL: {err}", file=sys.stderr)
        sys.exit(1)

    print(f"  OK: all {len(REGISTRY)} source pipelines simulate cleanly", flush=True)


if __name__ == "__main__":
    main()
