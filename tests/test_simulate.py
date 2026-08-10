"""Unit tests for synthsetup.simulate — mocked ES + Kibana endpoints.

Tests cover:
  - Happy path: all three pipelines return clean docs, no errors reported
  - Per-doc error path: one source returns an error doc; error names the source
  - HTTP error path: simulate returns non-200; error names the source and status
"""
from __future__ import annotations

import respx

from synthsetup.simulate import REGISTRY, run_simulate

ES = "https://es.example.com"
KB = "https://kb.example.com"
KEY = "fake-key"

# Version strings that will be returned by the mocked Kibana package endpoint.
_VERSIONS: dict[str, str] = {
    "cisco_asa": "2.34.0",
    "cisco_ios": "1.20.0",
    "panw": "5.5.0",
}


def _mock_versions() -> None:
    """Register respx mocks for all package-version lookups."""
    for pkg, ver in _VERSIONS.items():
        respx.get(f"{KB}/api/fleet/epm/packages/{pkg}").respond(
            json={"item": {"version": ver}}
        )


def _pipeline_url(pkg: str, dataset: str) -> str:
    ver = _VERSIONS[pkg]
    return f"{ES}/_ingest/pipeline/logs-{dataset}-{ver}/_simulate"


def _ok_response(n: int) -> dict:
    """Successful simulate response with n docs (no errors)."""
    return {
        "docs": [
            {"doc": {"_source": {"@timestamp": "2026-08-11T12:00:00Z"}, "_index": "x"}}
            for _ in range(n)
        ]
    }


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------

# Pinned sample counts per source — update both here AND in simulate.py when
# a new message type is added to a source's sample builder.
#   cisco_asa : 4 — asa_302013, asa_302014, asa_106023, asa_113005
#   cisco_ios : 5 — ios_login_success, ios_config_i, ios_link_updown,
#                   ios_lineproto_updown, ios_logginghost
#   panw      : 2 — panos_traffic, panos_threat
_EXPECTED_DOC_COUNTS: dict[str, int] = {
    "cisco_asa": 4,
    "cisco_ios": 5,
    "panw": 2,
}


@respx.mock
def test_happy_path_all_sources_ok():
    _mock_versions()
    for pkg, dataset, sample_fn in REGISTRY:
        n = len(sample_fn())
        # Assert pinned count so adding a format function without a sample fails fast.
        assert n == _EXPECTED_DOC_COUNTS[pkg], (
            f"{pkg}: expected {_EXPECTED_DOC_COUNTS[pkg]} sample docs, "
            f"got {n} — update _EXPECTED_DOC_COUNTS and the sample builder"
        )
        respx.post(_pipeline_url(pkg, dataset)).respond(json=_ok_response(n))

    errors = run_simulate(ES, KB, KEY)
    assert errors == [], f"Expected no errors, got: {errors}"


# ---------------------------------------------------------------------------
# Per-doc error path
# ---------------------------------------------------------------------------

@respx.mock
def test_doc_error_in_panw_surfaces_package_name():
    _mock_versions()
    # cisco_asa and cisco_ios succeed
    for pkg, dataset, sample_fn in REGISTRY:
        if pkg == "panw":
            continue
        respx.post(_pipeline_url(pkg, dataset)).respond(json=_ok_response(len(sample_fn())))

    # panw pipeline returns an error on the first doc
    panw_entry = next(e for e in REGISTRY if e[0] == "panw")
    _, panw_dataset, panw_fn = panw_entry
    n = len(panw_fn())
    error_response = {
        "docs": [
            {
                "error": {
                    "type": "parse_exception",
                    "reason": "failed to parse CSV field [message]",
                }
            }
        ]
        + [{"doc": {"_source": {}}} for _ in range(n - 1)]
    }
    respx.post(_pipeline_url("panw", panw_dataset)).respond(json=error_response)

    errors = run_simulate(ES, KB, KEY)
    assert errors, "Expected at least one error"
    assert any("panw" in e for e in errors), f"Expected 'panw' in error text: {errors}"
    assert any("parse_exception" in e for e in errors), (
        f"Expected error type in output: {errors}"
    )


@respx.mock
def test_doc_error_in_cisco_asa_surfaces_package_name():
    _mock_versions()
    for pkg, dataset, sample_fn in REGISTRY:
        if pkg == "cisco_asa":
            continue
        respx.post(_pipeline_url(pkg, dataset)).respond(json=_ok_response(len(sample_fn())))

    asa_entry = next(e for e in REGISTRY if e[0] == "cisco_asa")
    _, asa_dataset, asa_fn = asa_entry
    n = len(asa_fn())
    # Error nested inside "doc" (older ES format)
    error_response = {
        "docs": [
            {"doc": {"error": {"type": "grok_exception", "reason": "no match found"}}}
        ]
        + [{"doc": {"_source": {}}} for _ in range(n - 1)]
    }
    respx.post(_pipeline_url("cisco_asa", asa_dataset)).respond(json=error_response)

    errors = run_simulate(ES, KB, KEY)
    assert any("cisco_asa" in e for e in errors), f"Expected 'cisco_asa' in error: {errors}"


# ---------------------------------------------------------------------------
# HTTP error path
# ---------------------------------------------------------------------------

@respx.mock
def test_http_404_surfaces_source_name_and_status():
    _mock_versions()
    for pkg, dataset, sample_fn in REGISTRY:
        if pkg == "cisco_ios":
            continue
        respx.post(_pipeline_url(pkg, dataset)).respond(json=_ok_response(len(sample_fn())))

    ios_entry = next(e for e in REGISTRY if e[0] == "cisco_ios")
    _, ios_dataset, _ = ios_entry
    # Simulate pipeline not found (e.g. package not yet installed)
    respx.post(_pipeline_url("cisco_ios", ios_dataset)).respond(status_code=404, json={})

    errors = run_simulate(ES, KB, KEY)
    assert any("cisco_ios" in e for e in errors), f"Expected 'cisco_ios' in error: {errors}"
    assert any("404" in e for e in errors), f"Expected '404' in error: {errors}"


# ---------------------------------------------------------------------------
# Dropped-docs path
# ---------------------------------------------------------------------------

@respx.mock
def test_dropped_doc_count_mismatch_surfaces_error():
    _mock_versions()
    for pkg, dataset, sample_fn in REGISTRY:
        if pkg == "panw":
            continue
        respx.post(_pipeline_url(pkg, dataset)).respond(json=_ok_response(len(sample_fn())))

    panw_entry = next(e for e in REGISTRY if e[0] == "panw")
    _, panw_dataset, panw_fn = panw_entry
    n = len(panw_fn())
    # Return fewer docs than sent (simulates a drop processor)
    respx.post(_pipeline_url("panw", panw_dataset)).respond(json=_ok_response(n - 1))

    errors = run_simulate(ES, KB, KEY)
    assert any("panw" in e for e in errors), f"Expected 'panw' in error: {errors}"
