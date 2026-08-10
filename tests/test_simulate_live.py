"""Live integration test — verify all syslog pipelines simulate cleanly.

Requires live Elastic credentials in the environment:
    ES_URL, KIBANA_URL, ELASTIC_API_KEY

Marked @pytest.mark.live and skipped automatically when ES_URL is not set.
Run explicitly with:
    pytest -m live tests/test_simulate_live.py
"""
from __future__ import annotations

import os

import pytest

from synthsetup.simulate import REGISTRY, run_simulate


@pytest.mark.live
@pytest.mark.skipif(
    not os.environ.get("ES_URL"),
    reason="live credentials required (ES_URL not set)",
)
def test_all_pipelines_simulate_cleanly():
    """Every registered syslog source must parse through its ingest pipeline
    without errors or dropped documents."""
    errors = run_simulate(
        es_url=os.environ["ES_URL"],
        kibana_url=os.environ["KIBANA_URL"],
        api_key=os.environ["ELASTIC_API_KEY"],
    )
    assert errors == [], (
        f"Pipeline simulate gate failed for {len(errors)} check(s):\n"
        + "\n".join(f"  • {e}" for e in errors)
    )


@pytest.mark.live
@pytest.mark.skipif(
    not os.environ.get("ES_URL"),
    reason="live credentials required (ES_URL not set)",
)
def test_registry_covers_all_three_sources():
    """Smoke-check that the registry has entries for all three syslog sources."""
    packages = {entry[0] for entry in REGISTRY}
    assert "cisco_asa" in packages
    assert "cisco_ios" in packages
    assert "panw" in packages
