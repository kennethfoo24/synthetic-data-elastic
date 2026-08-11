from __future__ import annotations

import os
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import httpx

from synthgen.common.topology import load_topology as _load_topology

_TOPOLOGY_PATH = Path(__file__).parents[2] / "topology" / "network.yaml"


def _snmp_device_threshold() -> int:
    """Count non-database, non-meraki devices in topology — the expected SNMP device count."""
    topo = _load_topology(_TOPOLOGY_PATH)
    return len([d for d in topo.devices if d.role != "database" and d.vendor != "meraki"])


_SNMP_DEVICE_THRESHOLD = _snmp_device_threshold()


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


def check_snmp_devices(ctx: Ctx) -> str:
    """Verify SNMP metrics flowing: docs in last 5m and distinct device.name count from topology.

    Logstash polls snmpsim every 60 s via the bundled logstash-integration-snmp plugin
    and writes metrics to data stream metrics-snmp.device-default.  The terms agg on
    device.name confirms all topology devices are represented.  Under the built-in metrics
    ECS template, string fields map directly to keyword — there is no .keyword sub-field.

    The threshold is derived from topology (non-database, non-meraki devices) at import time
    so it stays in sync with the device roster automatically.
    """
    body = {
        "size": 0,
        "query": {"range": {"@timestamp": {"gte": "now-5m"}}},
        "aggs": {
            "device_names": {
                "terms": {"field": "device.name", "size": 100},
            }
        },
    }
    r = ctx.es().post("/metrics-snmp.device-default/_search", json=body)
    if r.status_code == 404:
        raise CheckFailed("data stream metrics-snmp.device-default does not exist")
    data = r.json()
    total = data.get("hits", {}).get("total", {}).get("value", 0)
    if total == 0:
        raise CheckFailed("0 docs in metrics-snmp.device-default in last 5m")
    buckets = data.get("aggregations", {}).get("device_names", {}).get("buckets", [])
    distinct = len(buckets)
    if distinct < _SNMP_DEVICE_THRESHOLD:
        raise CheckFailed(
            f"only {distinct} distinct device.name values in metrics-snmp.device-default"
            f" (need ≥ {_SNMP_DEVICE_THRESHOLD})"
        )
    return f"{total} SNMP metric docs in last 5m, {distinct} distinct devices"


def check_mongodb_metrics(ctx: Ctx) -> str:
    """Verify MongoDB status metrics flowing: docs in metrics-mongodb.status-default in last 5m.

    The mongodb.status stream is always enabled and fires every 10 s, so ≥ 1 doc
    within a 5-minute window is the minimum bar.  The data stream name format is
    metrics-<package>.<dataset>-<namespace> per Fleet convention.
    """
    r = ctx.es().post("/metrics-mongodb.status-default/_count", json={
        "query": {"range": {"@timestamp": {"gte": "now-5m"}}}})
    if r.status_code == 404:
        raise CheckFailed("data stream metrics-mongodb.status-default does not exist")
    count = r.json().get("count", 0)
    if count == 0:
        raise CheckFailed("0 docs in metrics-mongodb.status-default in last 5m")
    return f"{count} MongoDB status metric docs in last 5m"


def check_postgresql_metrics(ctx: Ctx) -> str:
    """Verify PostgreSQL database metrics flowing in metrics-postgresql.database-default.

    The postgresql.database stream fires every 10 s.  A 5-minute window should
    contain ≥ 1 doc for the postgres database on the primary.
    """
    r = ctx.es().post("/metrics-postgresql.database-default/_count", json={
        "query": {"range": {"@timestamp": {"gte": "now-5m"}}}})
    if r.status_code == 404:
        raise CheckFailed("data stream metrics-postgresql.database-default does not exist")
    count = r.json().get("count", 0)
    if count == 0:
        raise CheckFailed("0 docs in metrics-postgresql.database-default in last 5m")
    return f"{count} PostgreSQL database metric docs in last 5m"


def check_panw_log_types(ctx: Ctx) -> str:
    """Verify PANW log-type coverage: TRAFFIC, THREAT, and SYSTEM all present in last 15m.

    The PANW integration emits all three log types when the generator is active.
    A missing type indicates either a pipeline gap or a generator failure.
    The panw.panos.type field is a keyword mapped by the panw integration.
    """
    body = {
        "size": 0,
        "query": {"range": {"@timestamp": {"gte": "now-15m"}}},
        "aggs": {
            "log_types": {
                "terms": {"field": "panw.panos.type", "size": 20},
            }
        },
    }
    r = ctx.es().post("/logs-panw.panos-default/_search", json=body)
    if r.status_code == 404:
        raise CheckFailed("data stream logs-panw.panos-default does not exist")
    buckets = r.json().get("aggregations", {}).get("log_types", {}).get("buckets", [])
    found = {b["key"] for b in buckets}
    required = {"TRAFFIC", "THREAT", "SYSTEM"}
    missing = required - found
    if missing:
        raise CheckFailed(
            f"PANW log types missing from logs-panw.panos-default in last 15m: {sorted(missing)}"
        )
    return f"PANW log types present: {sorted(found & required)}"


def check_meraki_event_variety(ctx: Ctx) -> str:
    """Verify Meraki webhook events parse cleanly and show >= 2 distinct alert types.

    Two sub-checks:

    1. **Pipeline-error guard** — any doc with ``event.kind=pipeline_error`` in
       the last 15 minutes means the payload schema is wrong.  Fail hard so
       wire-format regressions are caught immediately.

    2. **Alert-type variety** — aggregates on ``cisco_meraki.alert_type`` (the
       ECS-mapped field the pipeline produces).  If that returns zero buckets,
       falls back to the raw ``json.alertType`` keyword.  Requires >= 2 distinct
       values so we know the generator is rotating alert types correctly.
    """
    ds = "logs-cisco_meraki.events-default"

    # 1. Pipeline-error guard (last 15 minutes)
    r_err = ctx.es().post(f"/{ds}/_count", json={
        "query": {
            "bool": {
                "must": [
                    {"term": {"event.kind": "pipeline_error"}},
                    {"range": {"@timestamp": {"gte": "now-15m"}}},
                ]
            }
        }
    })
    if r_err.status_code == 404:
        raise CheckFailed(f"data stream {ds} does not exist")
    err_count = r_err.json().get("count", 0)
    if err_count > 0:
        raise CheckFailed(
            f"{err_count} pipeline_error doc(s) in {ds} in last 15m — "
            "fix the webhook payload or ingest pipeline"
        )

    # 2. Alert-type variety
    def _agg_alert_types(field: str) -> list[str]:
        body = {
            "size": 0,
            "query": {"range": {"@timestamp": {"gte": "now-5m"}}},
            "aggs": {"alert_types": {"terms": {"field": field, "size": 20}}},
        }
        r = ctx.es().post(f"/{ds}/_search", json=body)
        if r.status_code != 200:
            return []
        return [
            b["key"]
            for b in r.json()
            .get("aggregations", {})
            .get("alert_types", {})
            .get("buckets", [])
        ]

    values = _agg_alert_types("event.action")
    used_field = "event.action"
    if not values:
        values = _agg_alert_types("cisco_meraki.event.alertTypeId")
        used_field = "cisco_meraki.event.alertTypeId"

    if len(values) < 2:
        raise CheckFailed(
            f"only {len(values)} distinct alert type(s) in {ds} "
            f"(field={used_field}, need >= 2)"
        )
    sample = ", ".join(sorted(values)[:3])
    return f"{len(values)} distinct Meraki alert types in last 5m ({used_field}): {sample}"


def check_ios_mnemonic_variety(ctx: Ctx) -> str:
    """Verify IOS mnemonic variety: >= 3 distinct event.code values in last 15m.

    The IOS generator emits multiple syslog mnemonics (LOGIN_SUCCESS, CONFIG_I,
    LOGGINGHOST_STARTSTOP, UPDOWN, etc.).  The cisco_ios integration maps the
    mnemonic to event.code.  Fewer than 3 distinct values suggests a pipeline gap.
    """
    body = {
        "size": 0,
        "query": {"range": {"@timestamp": {"gte": "now-15m"}}},
        "aggs": {
            "mnemonics": {
                "terms": {"field": "event.code", "size": 20},
            }
        },
    }
    r = ctx.es().post("/logs-cisco_ios.log-default/_search", json=body)
    if r.status_code == 404:
        raise CheckFailed("data stream logs-cisco_ios.log-default does not exist")
    buckets = r.json().get("aggregations", {}).get("mnemonics", {}).get("buckets", [])
    distinct = len(buckets)
    if distinct < 3:
        raise CheckFailed(
            f"only {distinct} distinct event.code values in logs-cisco_ios.log-default"
            " in last 15m (need ≥ 3)"
        )
    return f"{distinct} distinct IOS mnemonics (event.code) in last 15m"


def check_meraki_syslog_recent(ctx: Ctx) -> str:
    """Verify Meraki syslog lines (flows/urls/events) flowing into logs-cisco_meraki.log-default."""
    r = ctx.es().post("/logs-cisco_meraki.log-default/_count", json={
        "query": {"range": {"@timestamp": {"gte": "now-5m"}}}})
    if r.status_code == 404:
        raise CheckFailed("data stream logs-cisco_meraki.log-default does not exist")
    count = r.json().get("count", 0)
    if count == 0:
        raise CheckFailed("0 docs in logs-cisco_meraki.log-default in last 5m")
    return f"{count} Meraki syslog docs in last 5m"


def check_meraki_events_recent(ctx: Ctx) -> str:
    """Verify Meraki webhook events flowing into logs-cisco_meraki.events-default."""
    r = ctx.es().post("/logs-cisco_meraki.events-default/_count", json={
        "query": {"range": {"@timestamp": {"gte": "now-5m"}}}})
    if r.status_code == 404:
        raise CheckFailed("data stream logs-cisco_meraki.events-default does not exist")
    count = r.json().get("count", 0)
    if count == 0:
        raise CheckFailed("0 docs in logs-cisco_meraki.events-default in last 5m")
    return f"{count} Meraki webhook event docs in last 5m"


CHECKS: list[tuple[str, Callable[[Ctx], str]]] = [
    ("agent online in Fleet", check_agents_online),
    ("ASA logs flowing", check_asa_docs_recent),
    ("IOS logs flowing", check_ios_docs_recent),
    ("PANW logs flowing", check_panw_docs_recent),
    ("PANW log types (TRAFFIC/THREAT/SYSTEM)", check_panw_log_types),
    ("IOS mnemonic variety >= 3", check_ios_mnemonic_variety),
    ("NetFlow docs flowing", check_netflow_docs_recent),
    ("NetFlow edge pairs >= 10", check_netflow_edges),
    ("SNMP metrics flowing", check_snmp_devices),
    ("MongoDB metrics flowing", check_mongodb_metrics),
    ("PostgreSQL metrics flowing", check_postgresql_metrics),
    ("Meraki syslog flowing", check_meraki_syslog_recent),
    ("Meraki webhook events flowing", check_meraki_events_recent),
    ("Meraki event variety >= 2", check_meraki_event_variety),
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
