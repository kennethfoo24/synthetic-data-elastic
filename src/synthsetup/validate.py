from __future__ import annotations

import os
import sys
from collections.abc import Callable
from dataclasses import dataclass

import httpx


@dataclass
class Ctx:
    es_url: str
    kibana_url: str
    api_key: str

    def es(self) -> httpx.Client:
        return httpx.Client(base_url=self.es_url.rstrip("/"),
                            headers={"Authorization": f"ApiKey {self.api_key}"}, timeout=30)

    def kb(self) -> httpx.Client:
        return httpx.Client(base_url=self.kibana_url.rstrip("/"),
                            headers={"Authorization": f"ApiKey {self.api_key}",
                                     "kbn-xsrf": "true"}, timeout=30)


class CheckFailed(Exception):
    pass


def check_asa_docs_recent(ctx: Ctx) -> str:
    r = ctx.es().post("/logs-cisco_asa.log-default/_count", json={
        "query": {"range": {"@timestamp": {"gte": "now-5m"}}}})
    if r.status_code == 404:
        raise CheckFailed("data stream logs-cisco_asa.log-default does not exist")
    count = r.json().get("count", 0)
    if count == 0:
        raise CheckFailed("0 docs in logs-cisco_asa.log-default in last 5m")
    return f"{count} ASA docs in last 5m"


def check_agents_online(ctx: Ctx) -> str:
    r = ctx.kb().get("/api/fleet/agents", params={"kuery": "status:online"})
    items = r.json().get("items", [])
    if not items:
        raise CheckFailed("no online agents in Fleet")
    return f"{len(items)} agent(s) online"


CHECKS: list[tuple[str, Callable[[Ctx], str]]] = [
    ("agent online in Fleet", check_agents_online),
    ("ASA logs flowing", check_asa_docs_recent),
]


def main() -> None:
    ctx = Ctx(os.environ["ES_URL"], os.environ["KIBANA_URL"], os.environ["ELASTIC_API_KEY"])
    failed = 0
    for name, fn in CHECKS:
        try:
            detail = fn(ctx)
            print(f"  ✅ {name}: {detail}")
        except Exception as exc:  # noqa: BLE001
            print(f"  ❌ {name}: {exc}")
            failed += 1
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
