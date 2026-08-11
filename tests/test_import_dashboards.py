"""Tests for synthsetup.import_dashboards."""
from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
import respx

from synthsetup.import_dashboards import DASHBOARD_IDS, DASHBOARDS_DIR, import_dashboards

KB = "https://kb.example.com"
API_KEY = "test-api-key"

# ---------------------------------------------------------------------------
# NDJSON file structural tests
# ---------------------------------------------------------------------------

EXPECTED_IDS = {
    "synthnet-hpe-infrastructure",
    "synthnet-dell-infrastructure",
    "synthnet-network-overview",
}


def test_ndjson_files_exist():
    for dash_id in EXPECTED_IDS:
        # Map id to filename
        if "hpe" in dash_id:
            name = "hpe.ndjson"
        elif "dell" in dash_id:
            name = "dell.ndjson"
        else:
            name = "network-overview.ndjson"
        assert (DASHBOARDS_DIR / name).exists(), f"{name} not found in {DASHBOARDS_DIR}"


def test_all_ndjson_files_parse_as_valid_ndjson():
    """Each non-blank line in every NDJSON file must be valid JSON."""
    for path in sorted(DASHBOARDS_DIR.glob("*.ndjson")):
        for lineno, line in enumerate(path.read_text().splitlines(), start=1):
            if not line.strip():
                continue
            try:
                json.loads(line)
            except json.JSONDecodeError as exc:
                pytest.fail(f"{path.name} line {lineno}: invalid JSON — {exc}")


def test_dashboard_ids_match_expected_stable_ids():
    """Each NDJSON file must contain exactly the expected stable dashboard ID."""
    found_ids: set[str] = set()
    for path in sorted(DASHBOARDS_DIR.glob("*.ndjson")):
        for line in path.read_text().splitlines():
            if not line.strip():
                continue
            obj = json.loads(line)
            assert obj.get("type") == "dashboard", f"{path.name}: expected type=dashboard, got {obj.get('type')!r}"
            found_ids.add(obj["id"])
    assert found_ids == EXPECTED_IDS, f"Dashboard IDs mismatch: {found_ids} != {EXPECTED_IDS}"


def test_panels_json_is_a_string_not_a_nested_object():
    """panelsJSON must be a JSON-stringified string, not a nested object."""
    for path in sorted(DASHBOARDS_DIR.glob("*.ndjson")):
        for line in path.read_text().splitlines():
            if not line.strip():
                continue
            obj = json.loads(line)
            panels_json = obj["attributes"]["panelsJSON"]
            assert isinstance(panels_json, str), (
                f"{path.name}: panelsJSON must be a string (JSON-stringified array), "
                f"got {type(panels_json).__name__}"
            )
            # It must itself be valid JSON (an array of panels)
            parsed = json.loads(panels_json)
            assert isinstance(parsed, list), (
                f"{path.name}: panelsJSON decoded value must be a list, got {type(parsed).__name__}"
            )
            assert len(parsed) > 0, f"{path.name}: panelsJSON array must not be empty"


def test_each_dashboard_has_six_panels():
    """Each dashboard must contain exactly 6 panels."""
    for path in sorted(DASHBOARDS_DIR.glob("*.ndjson")):
        for line in path.read_text().splitlines():
            if not line.strip():
                continue
            obj = json.loads(line)
            panels = json.loads(obj["attributes"]["panelsJSON"])
            assert len(panels) == 6, f"{path.name}: expected 6 panels, got {len(panels)}"


def test_network_overview_panel6_is_markdown():
    """network-overview panel-6 must be a markdown scenario-annotations panel."""
    path = DASHBOARDS_DIR / "network-overview.ndjson"
    obj = json.loads(path.read_text())
    panels = json.loads(obj["attributes"]["panelsJSON"])
    panel6 = next((p for p in panels if p["panelIndex"] == "panel-6"), None)
    assert panel6 is not None, "panel-6 not found in network-overview"
    assert panel6["type"] == "markdown", (
        f"panel-6 type must be 'markdown', got {panel6['type']!r}"
    )
    md = panel6["embeddableConfig"]["attributes"]["markdown"]
    assert "Scenario" in md, "markdown content must reference scenario annotations"
    assert "PANW" in md or "ASA" in md, "markdown must list at least one scenario source"


def test_hpe_dell_panels_have_correct_vendor_filters():
    """HPE panels must filter device.vendor: hpe; Dell panels must filter device.vendor: dell."""
    for fname, vendor in [("hpe.ndjson", "hpe"), ("dell.ndjson", "dell")]:
        path = DASHBOARDS_DIR / fname
        obj = json.loads(path.read_text())
        panels = json.loads(obj["attributes"]["panelsJSON"])
        for panel in panels:
            state = panel["embeddableConfig"]["attributes"]["state"]
            query = state["query"]["query"]
            assert f"device.vendor: {vendor}" in query, (
                f"{fname} panel {panel['panelIndex']}: expected 'device.vendor: {vendor}' "
                f"in query, got {query!r}"
            )


def test_dashboard_ids_constant_matches_ndjson_files():
    """The DASHBOARD_IDS constant in import_dashboards.py must match the actual file IDs."""
    ndjson_ids: set[str] = set()
    for path in sorted(DASHBOARDS_DIR.glob("*.ndjson")):
        for line in path.read_text().splitlines():
            if not line.strip():
                continue
            obj = json.loads(line)
            ndjson_ids.add(obj["id"])
    assert set(DASHBOARD_IDS) == ndjson_ids


# ---------------------------------------------------------------------------
# import_dashboards() HTTP behaviour
# ---------------------------------------------------------------------------

_SUCCESS_RESPONSE = {"success": True, "successCount": 1, "errors": []}


@respx.mock
def test_import_dashboards_happy_path():
    """All NDJSON files imported successfully — no errors raised."""
    respx.post(f"{KB}/api/saved_objects/_import").respond(json=_SUCCESS_RESPONSE)
    # Should not raise
    import_dashboards(KB, API_KEY)


@respx.mock
def test_import_dashboards_idempotent_on_second_call():
    """Calling import_dashboards twice in a row must succeed (overwrite=true)."""
    route = respx.post(f"{KB}/api/saved_objects/_import").respond(json=_SUCCESS_RESPONSE)
    import_dashboards(KB, API_KEY)
    import_dashboards(KB, API_KEY)
    # Route should have been called twice per file per run: 3 files × 2 runs = 6
    assert route.call_count == 6


@respx.mock
def test_import_dashboards_non_200_raises_system_exit():
    """A non-200 HTTP response from Kibana must cause SystemExit(1)."""
    respx.post(f"{KB}/api/saved_objects/_import").respond(500, text="Internal Server Error")
    with pytest.raises(SystemExit) as exc_info:
        import_dashboards(KB, API_KEY)
    assert exc_info.value.code == 1


@respx.mock
def test_import_dashboards_api_error_in_response_raises_system_exit():
    """A 200 response with success=False must cause SystemExit(1)."""
    error_response = {
        "success": False,
        "successCount": 0,
        "errors": [{"type": "dashboard", "id": "synthnet-hpe-infrastructure", "error": {"type": "conflict"}}],
    }
    respx.post(f"{KB}/api/saved_objects/_import").respond(json=error_response)
    with pytest.raises(SystemExit) as exc_info:
        import_dashboards(KB, API_KEY)
    assert exc_info.value.code == 1


@respx.mock
def test_import_requests_carry_overwrite_param():
    """Each import request must include overwrite=true as a query param."""
    route = respx.post(f"{KB}/api/saved_objects/_import").respond(json=_SUCCESS_RESPONSE)
    import_dashboards(KB, API_KEY)
    for call in route.calls:
        url = str(call.request.url)
        assert "overwrite=true" in url, f"overwrite=true missing from URL: {url}"


@respx.mock
def test_import_requests_carry_auth_and_xsrf_headers():
    """Each import request must carry Authorization and kbn-xsrf headers."""
    route = respx.post(f"{KB}/api/saved_objects/_import").respond(json=_SUCCESS_RESPONSE)
    import_dashboards(KB, API_KEY)
    for call in route.calls:
        headers = call.request.headers
        assert headers.get("authorization") == f"ApiKey {API_KEY}"
        assert headers.get("kbn-xsrf") == "true"


@respx.mock
def test_import_uses_multipart_form_data():
    """Each import request must use multipart/form-data with a 'file' field."""
    route = respx.post(f"{KB}/api/saved_objects/_import").respond(json=_SUCCESS_RESPONSE)
    import_dashboards(KB, API_KEY)
    for call in route.calls:
        content_type = call.request.headers.get("content-type", "")
        assert "multipart/form-data" in content_type, (
            f"Expected multipart/form-data Content-Type, got: {content_type!r}"
        )
        # The raw body must contain the multipart 'file' field name
        body = call.request.content
        assert b'name="file"' in body, "multipart body must contain a 'file' field"
