"""Unit tests for synthsetup.backfill.

Covers:
- Seam continuity: generate_for_tick equals generate_batch for (topo, t, seed)
- Bulk body format: correct NDJSON action + source pairs
- Bulk chunking: N docs fire ceil(N/CHUNK_SIZE) POST /_bulk requests
- _flush_bulk error paths: HTTP error and per-doc error both raise RuntimeError
- Mapping validation hard-fail: unknown field causes sys.exit(1)
- Mapping validation passes: all fields known succeeds silently
- Mapping validation 404: missing index causes sys.exit(1)
- Dry-run: no POST to _bulk and no delete_by_query
- CLI arg defaults: --days=7, --sources=all, --dry-run=False
- CLI flag override: --days, --sources, --dry-run all honoured
"""
from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import respx

from synthgen import GLOBAL_SEED
from synthgen.common.topology import load_topology
from synthgen.syslog_gen import asa_source, panw_source
from synthsetup.backfill import (
    BULK_CHUNK,
    _backfill_log_source,
    _build_bulk_body,
    _bulk_in_chunks,
    _flush_bulk,
    generate_for_tick,
)
from synthsetup.validate import Ctx, validate_mappings

_TOPO_PATH = Path(__file__).parents[1] / "topology" / "network.yaml"
_TOPO = load_topology(_TOPO_PATH)

CTX = Ctx(es_url="https://es.example.com", kibana_url="https://kb.example.com", api_key="k")
_T = datetime(2026, 8, 11, 12, 0, 0, tzinfo=UTC)

# ---------------------------------------------------------------------------
# Seam continuity
# ---------------------------------------------------------------------------


def test_seam_continuity_cisco_asa():
    """generate_for_tick must equal generate_batch for the same (topo, t, seed)."""
    backfill_lines = generate_for_tick("cisco_asa", _TOPO, _T, GLOBAL_SEED)
    live_lines = asa_source.generate_batch(_TOPO, _T, GLOBAL_SEED)
    assert backfill_lines == live_lines, (
        "Seam broken: generate_for_tick and generate_batch differ at the same tick"
    )


def test_seam_continuity_panw():
    """generate_for_tick must equal panw_source.generate_batch for the same tick."""
    assert (
        generate_for_tick("panw", _TOPO, _T, GLOBAL_SEED)
        == panw_source.generate_batch(_TOPO, _T, GLOBAL_SEED)
    )


def test_seam_continuity_all_sources():
    """Every registered source returns the same batch via generate_for_tick."""
    from synthgen.syslog_gen import ios_source, meraki_source

    for source, direct_fn in [
        ("cisco_asa", asa_source.generate_batch),
        ("cisco_ios", ios_source.generate_batch),
        ("panw", panw_source.generate_batch),
        ("cisco_meraki", meraki_source.generate_batch),
    ]:
        assert generate_for_tick(source, _TOPO, _T, GLOBAL_SEED) == direct_fn(_TOPO, _T, GLOBAL_SEED), (
            f"Seam broken for source={source!r}"
        )


def test_seam_unknown_source_raises():
    with pytest.raises(ValueError, match="Unknown log source"):
        generate_for_tick("bogus_source", _TOPO, _T, GLOBAL_SEED)


# ---------------------------------------------------------------------------
# Bulk body format
# ---------------------------------------------------------------------------


def test_build_bulk_body_ndjson_structure():
    docs = [("my-index", {"@timestamp": "2026-01-01T00:00:00+00:00", "message": "hello"})]
    body = _build_bulk_body(docs).decode()
    lines = body.strip().split("\n")
    assert len(lines) == 2
    action = json.loads(lines[0])
    assert action == {"index": {"_index": "my-index"}}
    source = json.loads(lines[1])
    assert source["message"] == "hello"


def test_build_bulk_body_multiple_docs():
    docs = [("idx-a", {"x": 1}), ("idx-b", {"x": 2})]
    body = _build_bulk_body(docs).decode()
    lines = body.strip().split("\n")
    assert len(lines) == 4  # 2 docs × 2 lines each
    assert json.loads(lines[0])["index"]["_index"] == "idx-a"
    assert json.loads(lines[2])["index"]["_index"] == "idx-b"


# ---------------------------------------------------------------------------
# Bulk chunking
# ---------------------------------------------------------------------------


@respx.mock
def test_bulk_chunking_correct_request_count():
    """1050 docs at BULK_CHUNK=500 must fire exactly 3 bulk requests."""
    n_docs = BULK_CHUNK * 2 + 50  # 1050
    docs = [("idx", {"@timestamp": "t", "x": i}) for i in range(n_docs)]

    bulk_route = respx.post("https://es.example.com/_bulk").respond(
        json={"errors": False, "items": []}
    )

    _bulk_in_chunks(CTX, docs, dry_run=False)

    assert bulk_route.call_count == 3, (
        f"Expected 3 bulk requests (500+500+50), got {bulk_route.call_count}"
    )


@respx.mock
def test_bulk_chunking_exactly_one_chunk():
    """Exactly BULK_CHUNK docs must fire exactly 1 request."""
    docs = [("idx", {"@timestamp": "t", "x": i}) for i in range(BULK_CHUNK)]
    route = respx.post("https://es.example.com/_bulk").respond(
        json={"errors": False, "items": []}
    )
    _bulk_in_chunks(CTX, docs, dry_run=False)
    assert route.call_count == 1


@respx.mock
def test_bulk_chunking_dry_run_fires_nothing():
    """dry_run=True: _bulk_in_chunks must not call /_bulk at all."""
    docs = [("idx", {"@timestamp": "t", "x": i}) for i in range(BULK_CHUNK * 2)]
    route = respx.post("https://es.example.com/_bulk").respond(
        json={"errors": False, "items": []}
    )
    _bulk_in_chunks(CTX, docs, dry_run=True)
    assert route.call_count == 0


# ---------------------------------------------------------------------------
# _flush_bulk error paths
# ---------------------------------------------------------------------------


@respx.mock
def test_flush_bulk_raises_on_http_error():
    respx.post("https://es.example.com/_bulk").respond(status_code=500, json={})
    with pytest.raises(RuntimeError, match="500"):
        _flush_bulk(CTX, [("idx", {"@timestamp": "t"})])


@respx.mock
def test_flush_bulk_raises_on_doc_level_error():
    respx.post("https://es.example.com/_bulk").respond(json={
        "errors": True,
        "items": [
            {"index": {"error": {"type": "mapper_exception", "reason": "field type mismatch"}}}
        ],
    })
    with pytest.raises(RuntimeError, match="mapper_exception"):
        _flush_bulk(CTX, [("idx", {"@timestamp": "t"})])


@respx.mock
def test_flush_bulk_raises_when_errors_flag_set_no_detail():
    """errors=True with no parseable per-item error still raises RuntimeError."""
    respx.post("https://es.example.com/_bulk").respond(json={
        "errors": True,
        "items": [{"index": {}}],  # no error detail
    })
    with pytest.raises(RuntimeError, match="Bulk indexing errors"):
        _flush_bulk(CTX, [("idx", {"@timestamp": "t"})])


# ---------------------------------------------------------------------------
# Mapping validation
# ---------------------------------------------------------------------------

_GOOD_MAPPING = {
    ".ds-logs-netflow.log-default-000001": {
        "mappings": {
            "properties": {
                "@timestamp": {"type": "date"},
                "source": {
                    "properties": {
                        "ip": {"type": "ip"},
                        "port": {"type": "integer"},
                    }
                },
                "destination": {
                    "properties": {
                        "ip": {"type": "ip"},
                        "port": {"type": "integer"},
                    }
                },
                "network": {
                    "properties": {
                        "transport": {"type": "keyword"},
                        "bytes": {"type": "long"},
                        "packets": {"type": "long"},
                    }
                },
                "event": {
                    "properties": {
                        "kind": {"type": "keyword"},
                        "category": {"type": "keyword"},
                    }
                },
            }
        }
    }
}

_GOOD_DOC = {
    "@timestamp": "2026-01-01T00:00:00+00:00",
    "source": {"ip": "1.2.3.4", "port": 12345},
    "destination": {"ip": "5.6.7.8", "port": 443},
    "network": {"transport": "tcp", "bytes": 1000, "packets": 10},
    "event": {"kind": "event", "category": ["network"]},
}


@respx.mock
def test_validate_mappings_passes_on_known_fields():
    """validate_mappings should not raise when all fields are in the mapping."""
    respx.get("https://es.example.com/logs-netflow.log-default/_mapping").respond(
        json=_GOOD_MAPPING
    )
    validate_mappings(CTX, "logs-netflow.log-default", _GOOD_DOC)  # must not raise


@respx.mock
def test_validate_mappings_hard_fails_on_unknown_field(capsys):
    """validate_mappings must sys.exit(1) and name the unknown field in stderr."""
    respx.get("https://es.example.com/logs-netflow.log-default/_mapping").respond(
        json=_GOOD_MAPPING
    )
    bad_doc = {**_GOOD_DOC, "ghost_field": "not_in_mapping"}
    with pytest.raises(SystemExit) as exc_info:
        validate_mappings(CTX, "logs-netflow.log-default", bad_doc)
    assert exc_info.value.code != 0
    captured = capsys.readouterr()
    assert "ghost_field" in captured.err, f"Field name missing from stderr: {captured.err}"


@respx.mock
def test_validate_mappings_hard_fails_on_nested_unknown_field(capsys):
    """An unknown nested field (e.g. source.ghost) must also cause sys.exit(1)."""
    respx.get("https://es.example.com/logs-netflow.log-default/_mapping").respond(
        json=_GOOD_MAPPING
    )
    bad_doc = {"@timestamp": "t", "source": {"ip": "1.2.3.4", "ghost_nested": "bad"}}
    with pytest.raises(SystemExit) as exc_info:
        validate_mappings(CTX, "logs-netflow.log-default", bad_doc)
    assert exc_info.value.code != 0
    captured = capsys.readouterr()
    assert "ghost_nested" in captured.err


@respx.mock
def test_validate_mappings_404_index_exits(capsys):
    """validate_mappings must sys.exit(1) when the index does not exist."""
    respx.get("https://es.example.com/missing-index/_mapping").respond(status_code=404, json={})
    with pytest.raises(SystemExit) as exc_info:
        validate_mappings(CTX, "missing-index", {"@timestamp": "t"})
    assert exc_info.value.code != 0


# ---------------------------------------------------------------------------
# Dry-run: no writes
# ---------------------------------------------------------------------------


@respx.mock
def test_dry_run_no_bulk_no_delete():
    """_backfill_log_source with dry_run=True must not call _bulk or _delete_by_query."""
    bulk_route = respx.post("https://es.example.com/_bulk").respond(
        json={"errors": False, "items": []}
    )
    delete_route = respx.post(
        "https://es.example.com/logs-cisco_asa.log-default/_delete_by_query"
    ).respond(json={"deleted": 0})

    start = _T
    end = _T + timedelta(seconds=61)  # one stride tick only

    _backfill_log_source(
        CTX, _TOPO,
        "cisco_asa", "logs-cisco_asa.log-default", asa_source.generate_batch,
        start, end,
        dry_run=True,
    )

    assert bulk_route.call_count == 0, "dry-run must not POST to /_bulk"
    assert delete_route.call_count == 0, "dry-run must not POST to /_delete_by_query"


@respx.mock
def test_dry_run_returns_nonzero_doc_count():
    """dry_run=True must still return a doc count (for planning output)."""
    # No routes registered; any HTTP call would raise
    start = _T
    end = _T + timedelta(seconds=61)

    count = _backfill_log_source(
        CTX, _TOPO,
        "cisco_asa", "logs-cisco_asa.log-default", asa_source.generate_batch,
        start, end,
        dry_run=True,
    )
    assert count > 0, "dry-run should still report a non-zero planned doc count"


# ---------------------------------------------------------------------------
# CLI arg handling
# ---------------------------------------------------------------------------


def test_cli_defaults(monkeypatch):
    """Parser defaults: --days=7, --sources=all, --dry-run=False."""
    monkeypatch.setattr("sys.argv", ["backfill"])
    monkeypatch.setenv("ES_URL", "https://es.example.com")
    monkeypatch.setenv("ELASTIC_API_KEY", "test-key")

    captured: dict = {}

    def mock_run(ctx: object, days: int = 7, sources: str = "all", dry_run: bool = False) -> dict:
        captured.update({"days": days, "sources": sources, "dry_run": dry_run})
        return {}

    monkeypatch.setattr("synthsetup.backfill.run_backfill", mock_run)

    from synthsetup.backfill import main
    main()

    assert captured["days"] == 7
    assert captured["sources"] == "all"
    assert captured["dry_run"] is False


def test_cli_dry_run_and_overrides(monkeypatch):
    """--dry-run, --days, and --sources flags are all honoured."""
    monkeypatch.setattr("sys.argv", ["backfill", "--dry-run", "--days", "3", "--sources", "logs"])

    captured: dict = {}

    def mock_run(ctx: object, days: int = 7, sources: str = "all", dry_run: bool = False) -> dict:
        captured.update({"days": days, "sources": sources, "dry_run": dry_run})
        return {}

    monkeypatch.setattr("synthsetup.backfill.run_backfill", mock_run)

    from synthsetup.backfill import main
    main()

    assert captured["days"] == 3
    assert captured["sources"] == "logs"
    assert captured["dry_run"] is True


def test_cli_metrics_source(monkeypatch):
    """--sources metrics is accepted."""
    monkeypatch.setattr("sys.argv", ["backfill", "--dry-run", "--sources", "metrics"])

    captured: dict = {}

    def mock_run(ctx: object, days: int = 7, sources: str = "all", dry_run: bool = False) -> dict:
        captured.update({"sources": sources})
        return {}

    monkeypatch.setattr("synthsetup.backfill.run_backfill", mock_run)

    from synthsetup.backfill import main
    main()

    assert captured["sources"] == "metrics"


def test_cli_invalid_source_exits(monkeypatch):
    """--sources with an invalid value must cause argparse to exit nonzero."""
    monkeypatch.setattr("sys.argv", ["backfill", "--sources", "invalid"])
    from synthsetup.backfill import main
    with pytest.raises(SystemExit) as exc_info:
        main()
    assert exc_info.value.code != 0
