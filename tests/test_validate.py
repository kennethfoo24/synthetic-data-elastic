import pytest
import respx

from synthsetup.validate import (
    CheckFailed,
    Ctx,
    check_agents_online,
    check_asa_docs_recent,
    check_ios_docs_recent,
    check_netflow_docs_recent,
    check_netflow_edges,
    check_panw_docs_recent,
    check_snmp_devices,
)

CTX = Ctx(es_url="https://es.example.com", kibana_url="https://kb.example.com", api_key="k")

@respx.mock
def test_asa_check_passes_with_recent_docs():
    respx.post("https://es.example.com/logs-cisco_asa.log-default/_count").respond(
        json={"count": 42})
    assert "42" in check_asa_docs_recent(CTX)

@respx.mock
def test_asa_check_fails_with_zero_docs():
    respx.post("https://es.example.com/logs-cisco_asa.log-default/_count").respond(
        json={"count": 0})
    try:
        check_asa_docs_recent(CTX)
        assert False, "should have raised"
    except AssertionError:
        raise
    except Exception as exc:  # noqa: BLE001
        assert "0 docs" in str(exc)

@respx.mock
def test_agents_online():
    respx.get("https://kb.example.com/api/fleet/agent_policies").respond(
        json={"items": [{"id": "pol-1", "name": "synthetic-network"}]})
    respx.get("https://kb.example.com/api/fleet/agents").respond(
        json={"items": [{"status": "online", "policy_id": "pol-1"}], "total": 1})
    result = check_agents_online(CTX)
    assert "online" in result
    assert "synthetic-network" in result


@respx.mock
def test_agents_online_wrong_policy_filtered_out():
    respx.get("https://kb.example.com/api/fleet/agent_policies").respond(
        json={"items": [{"id": "pol-1", "name": "synthetic-network"}]})
    respx.get("https://kb.example.com/api/fleet/agents").respond(
        json={"items": [{"status": "online", "policy_id": "other-pol"}], "total": 1})
    with pytest.raises(CheckFailed, match="no online agents enrolled"):
        check_agents_online(CTX)


@respx.mock
def test_agents_online_policy_not_found():
    respx.get("https://kb.example.com/api/fleet/agent_policies").respond(
        json={"items": []})
    with pytest.raises(CheckFailed, match="not found"):
        check_agents_online(CTX)


@respx.mock
def test_ios_check_passes_with_recent_docs():
    respx.post("https://es.example.com/logs-cisco_ios.log-default/_count").respond(
        json={"count": 17})
    assert "17" in check_ios_docs_recent(CTX)


@respx.mock
def test_ios_check_fails_with_zero_docs():
    respx.post("https://es.example.com/logs-cisco_ios.log-default/_count").respond(
        json={"count": 0})
    with pytest.raises(CheckFailed, match="0 docs"):
        check_ios_docs_recent(CTX)


@respx.mock
def test_ios_check_fails_when_stream_missing():
    respx.post("https://es.example.com/logs-cisco_ios.log-default/_count").respond(
        status_code=404, json={})
    with pytest.raises(CheckFailed, match="does not exist"):
        check_ios_docs_recent(CTX)


@respx.mock
def test_panw_check_passes_with_recent_docs():
    respx.post("https://es.example.com/logs-panw.panos-default/_count").respond(
        json={"count": 99})
    assert "99" in check_panw_docs_recent(CTX)


@respx.mock
def test_panw_check_fails_with_zero_docs():
    respx.post("https://es.example.com/logs-panw.panos-default/_count").respond(
        json={"count": 0})
    with pytest.raises(CheckFailed, match="0 docs"):
        check_panw_docs_recent(CTX)


@respx.mock
def test_panw_check_fails_when_stream_missing():
    respx.post("https://es.example.com/logs-panw.panos-default/_count").respond(
        status_code=404, json={})
    with pytest.raises(CheckFailed, match="does not exist"):
        check_panw_docs_recent(CTX)


# ---------------------------------------------------------------------------
# NetFlow: doc-count check
# ---------------------------------------------------------------------------

@respx.mock
def test_netflow_check_passes_with_recent_docs():
    respx.post("https://es.example.com/logs-netflow.log-default/_count").respond(
        json={"count": 100})
    result = check_netflow_docs_recent(CTX)
    assert "100" in result


@respx.mock
def test_netflow_check_fails_with_zero_docs():
    respx.post("https://es.example.com/logs-netflow.log-default/_count").respond(
        json={"count": 0})
    with pytest.raises(CheckFailed, match="0 docs"):
        check_netflow_docs_recent(CTX)


@respx.mock
def test_netflow_check_fails_when_stream_missing():
    respx.post("https://es.example.com/logs-netflow.log-default/_count").respond(
        status_code=404, json={})
    with pytest.raises(CheckFailed, match="does not exist"):
        check_netflow_docs_recent(CTX)


# ---------------------------------------------------------------------------
# NetFlow: edge-pair (src→dst) check
# ---------------------------------------------------------------------------

def _edge_response(n_src: int, n_dst_each: int) -> dict:
    """Build a fake ES aggregation response with n_src × n_dst_each pairs."""
    return {
        "aggregations": {
            "src_ips": {
                "buckets": [
                    {
                        "key": f"10.0.0.{i}",
                        "doc_count": 5,
                        "dst_ips": {
                            "buckets": [
                                {"key": f"10.0.1.{j}", "doc_count": 1}
                                for j in range(n_dst_each)
                            ]
                        },
                    }
                    for i in range(n_src)
                ]
            }
        }
    }


@respx.mock
def test_netflow_edges_passes_with_12_pairs():
    respx.post("https://es.example.com/logs-netflow.log-default/_search").respond(
        json=_edge_response(6, 2))  # 6 × 2 = 12 pairs
    result = check_netflow_edges(CTX)
    assert "12" in result


@respx.mock
def test_netflow_edges_passes_at_exactly_ten():
    respx.post("https://es.example.com/logs-netflow.log-default/_search").respond(
        json=_edge_response(5, 2))  # 5 × 2 = 10 pairs
    result = check_netflow_edges(CTX)
    assert "10" in result


@respx.mock
def test_netflow_edges_fails_with_nine_pairs():
    respx.post("https://es.example.com/logs-netflow.log-default/_search").respond(
        json=_edge_response(3, 3))  # 3 × 3 = 9 pairs
    with pytest.raises(CheckFailed, match="need"):
        check_netflow_edges(CTX)


@respx.mock
def test_netflow_edges_fails_when_stream_missing():
    respx.post("https://es.example.com/logs-netflow.log-default/_search").respond(
        status_code=404, json={})
    with pytest.raises(CheckFailed, match="does not exist"):
        check_netflow_edges(CTX)


# ---------------------------------------------------------------------------
# SNMP devices check
# ---------------------------------------------------------------------------

def _snmp_search_response(total: int, device_names: list[str]) -> dict:
    """Build a fake ES search response with terms agg for device.name.keyword."""
    return {
        "hits": {"total": {"value": total}},
        "aggregations": {
            "device_names": {
                "buckets": [{"key": n, "doc_count": 3} for n in device_names],
            }
        },
    }


@respx.mock
def test_snmp_check_passes_with_20_devices():
    names = [f"device-{i:02d}" for i in range(20)]
    respx.post(
        "https://es.example.com/metrics-snmp.device-default/_search"
    ).respond(json=_snmp_search_response(600, names))
    result = check_snmp_devices(CTX)
    assert "600" in result
    assert "20" in result


@respx.mock
def test_snmp_check_passes_at_exactly_18_devices():
    names = [f"device-{i:02d}" for i in range(18)]
    respx.post(
        "https://es.example.com/metrics-snmp.device-default/_search"
    ).respond(json=_snmp_search_response(54, names))
    result = check_snmp_devices(CTX)
    assert "18" in result


@respx.mock
def test_snmp_check_fails_with_zero_docs():
    respx.post(
        "https://es.example.com/metrics-snmp.device-default/_search"
    ).respond(json=_snmp_search_response(0, []))
    with pytest.raises(CheckFailed, match="0 docs"):
        check_snmp_devices(CTX)


@respx.mock
def test_snmp_check_fails_with_fewer_than_18_devices():
    names = [f"device-{i:02d}" for i in range(15)]
    respx.post(
        "https://es.example.com/metrics-snmp.device-default/_search"
    ).respond(json=_snmp_search_response(45, names))
    with pytest.raises(CheckFailed, match="need"):
        check_snmp_devices(CTX)


@respx.mock
def test_snmp_check_fails_when_stream_missing():
    respx.post(
        "https://es.example.com/metrics-snmp.device-default/_search"
    ).respond(status_code=404, json={})
    with pytest.raises(CheckFailed, match="does not exist"):
        check_snmp_devices(CTX)
