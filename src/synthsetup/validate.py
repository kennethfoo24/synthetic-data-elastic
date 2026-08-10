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


AGENT_POLICY = "synthetic-network"


def check_asa_docs_recent(ctx: Ctx) -> str:
    r = ctx.es().post("/logs-cisco_asa.log-default/_count", json={
        "query": {"range": {"@timestamp": {"gte": "now-5m"}}}})
    if r.status_code == 404:
        raise CheckFailed("data stream logs-cisco_asa.log-default does not exist")
    count = r.json().get("count", 0)
    if count == 0:
        raise CheckFailed("0 docs in logs-cisco_asa.log-default in last 5m")
    return f"{count} ASA docs in last 5m"


def check_ios_docs_recent(ctx: Ctx) -> str:
    r = ctx.es().post("/logs-cisco_ios.log-default/_count", json={
        "query": {"range": {"@timestamp": {"gte": "now-5m"}}}})
    if r.status_code == 404:
        raise CheckFailed("data stream logs-cisco_ios.log-default does not exist")
    count = r.json().get("count", 0)
    if count == 0:
        raise CheckFailed("0 docs in logs-cisco_ios.log-default in last 5m")
    return f"{count} IOS docs in last 5m"


def check_panw_docs_recent(ctx: Ctx) -> str:
    r = ctx.es().post("/logs-panw.panos-default/_count", json={
        "query": {"range": {"@timestamp": {"gte": "now-5m"}}}})
    if r.status_code == 404:
        raise CheckFailed("data stream logs-panw.panos-default does not exist")
    count = r.json().get("count", 0)
    if count == 0:
        raise CheckFailed("0 docs in logs-panw.panos-default in last 5m")
    return f"{count} PANW docs in last 5m"


def check_agents_online(ctx: Ctx) -> str:
    rp = ctx.kb().get("/api/fleet/agent_policies",
                      params={"kuery": f'name:"{AGENT_POLICY}"'})
    policies = rp.json().get("items", [])
    matching = [p for p in policies if p.get("name") == AGENT_POLICY]
    if not matching:
        raise CheckFailed(f'agent policy "{AGENT_POLICY}" not found')
    policy_id = matching[0]["id"]

    r = ctx.kb().get("/api/fleet/agents", params={"kuery": "status:online"})
    items = [a for a in r.json().get("items", []) if a.get("policy_id") == policy_id]
    if not items:
        raise CheckFailed(f"no online agents enrolled in policy {AGENT_POLICY}")
    return f"{len(items)} agent(s) online in policy {AGENT_POLICY}"


def check_netflow_docs_recent(ctx: Ctx) -> str:
    r = ctx.es().post("/logs-netflow.log-default/_count", json={
        "query": {"range": {"@timestamp": {"gte": "now-5m"}}}})
    if r.status_code == 404:
        raise CheckFailed("data stream logs-netflow.log-default does not exist")
    count = r.json().get("count", 0)
    if count == 0:
        raise CheckFailed("0 docs in logs-netflow.log-default in last 5m")
    return f"{count} NetFlow docs in last 5m"


def check_netflow_edges(ctx: Ctx) -> str:
    """Verify ≥ 10 distinct source.ip → destination.ip pairs in the last 5 minutes.

    This is the edge-matrix query the MCP app uses to build the network flow graph.
    Confirming ≥ 10 pairs proves that multiple flows from the topology are visible.
    """
    body = {
        "size": 0,
        "query": {"range": {"@timestamp": {"gte": "now-5m"}}},
        "aggs": {
            "src_ips": {
                "terms": {"field": "source.ip", "size": 100},
                "aggs": {
                    "dst_ips": {
                        "terms": {"field": "destination.ip", "size": 100},
                    }
                },
            }
        },
    }
    r = ctx.es().post("/logs-netflow.log-default/_search", json=body)
    if r.status_code == 404:
        raise CheckFailed("data stream logs-netflow.log-default does not exist")
    pair_count = sum(
        len(src_b.get("dst_ips", {}).get("buckets", []))
        for src_b in r.json().get("aggregations", {}).get("src_ips", {}).get("buckets", [])
    )
    if pair_count < 10:
        raise CheckFailed(
            f"only {pair_count} distinct src→dst pairs in logs-netflow.log-default (need ≥ 10)"
        )
    return f"{pair_count} distinct src→dst flow pairs in last 5m"


CHECKS: list[tuple[str, Callable[[Ctx], str]]] = [
    ("agent online in Fleet", check_agents_online),
    ("ASA logs flowing", check_asa_docs_recent),
    ("IOS logs flowing", check_ios_docs_recent),
    ("PANW logs flowing", check_panw_docs_recent),
    ("NetFlow docs flowing", check_netflow_docs_recent),
    ("NetFlow edge pairs >= 10", check_netflow_edges),
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
