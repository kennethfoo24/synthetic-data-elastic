"""Import custom dashboards via Kibana Saved Objects _import API."""
from __future__ import annotations

import os
import sys
from pathlib import Path

import httpx

DASHBOARDS_DIR = Path(__file__).parents[2] / "setup" / "dashboards"
DASHBOARD_IDS = [
    "synthnet-hpe-infrastructure",
    "synthnet-dell-infrastructure",
    "synthnet-network-overview",
]


def import_dashboards(kibana_url: str, api_key: str) -> None:
    client = httpx.Client(
        base_url=kibana_url.rstrip("/"),
        headers={"Authorization": f"ApiKey {api_key}", "kbn-xsrf": "true"},
        timeout=60,
    )
    for ndjson_path in sorted(DASHBOARDS_DIR.glob("*.ndjson")):
        ndjson_content = ndjson_path.read_text()
        r = client.post(
            "/api/saved_objects/_import",
            params={"overwrite": "true"},
            content=ndjson_content,
            headers={
                "Authorization": f"ApiKey {api_key}",
                "kbn-xsrf": "true",
                "Content-Type": "application/ndjson",
            },
        )
        if r.status_code not in (200, 201):
            print(
                f"ERROR importing {ndjson_path.name}: {r.status_code} {r.text}",
                file=sys.stderr,
            )
            sys.exit(1)
        result = r.json()
        if not result.get("success"):
            errors = result.get("errors", [])
            print(f"ERROR importing {ndjson_path.name}: {errors}", file=sys.stderr)
            sys.exit(1)
        count = result.get("successCount", 0)
        print(f"  ✅ {ndjson_path.name}: {count} objects imported")


def main() -> None:
    kibana_url = os.environ["KIBANA_URL"]
    api_key = os.environ["ELASTIC_API_KEY"]
    print("==> importing custom dashboards")
    import_dashboards(kibana_url, api_key)
    print("==> done")


if __name__ == "__main__":
    main()
