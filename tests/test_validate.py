import httpx
import pytest
import respx

from synthsetup.validate import (
    _SNMP_DEVICE_THRESHOLD,
    CheckFailed,
    Ctx,
    check_agents_online,
    check_asa_docs_recent,
    check_ios_docs_recent,
    check_ios_mnemonic_variety,
    check_meraki_event_variety,
    check_meraki_events_recent,
    check_meraki_syslog_recent,
    check_netflow_docs_recent,
    check_netflow_edges,
    check_panw_docs_recent,
    check_panw_log_types,
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
def test_snmp_check_passes_at_exactly_threshold_devices():
    """Passes when device count equals the topology-derived threshold (currently 20)."""
    names = [f"device-{i:02d}" for i in range(_SNMP_DEVICE_THRESHOLD)]
    respx.post(
        "https://es.example.com/metrics-snmp.device-default/_search"
    ).respond(json=_snmp_search_response(_SNMP_DEVICE_THRESHOLD * 3, names))
    result = check_snmp_devices(CTX)
    assert str(_SNMP_DEVICE_THRESHOLD) in result


@respx.mock
def test_snmp_check_fails_with_zero_docs():
    respx.post(
        "https://es.example.com/metrics-snmp.device-default/_search"
    ).respond(json=_snmp_search_response(0, []))
    with pytest.raises(CheckFailed, match="0 docs"):
        check_snmp_devices(CTX)


@respx.mock
def test_snmp_check_fails_below_threshold():
    """Fails when device count is below the topology-derived threshold."""
    names = [f"device-{i:02d}" for i in range(_SNMP_DEVICE_THRESHOLD - 5)]
    respx.post(
        "https://es.example.com/metrics-snmp.device-default/_search"
    ).respond(json=_snmp_search_response(len(names) * 3, names))
    with pytest.raises(CheckFailed, match="need"):
        check_snmp_devices(CTX)


@respx.mock
def test_snmp_check_fails_when_stream_missing():
    respx.post(
        "https://es.example.com/metrics-snmp.device-default/_search"
    ).respond(status_code=404, json={})
    with pytest.raises(CheckFailed, match="does not exist"):
        check_snmp_devices(CTX)


# ---------------------------------------------------------------------------
# Meraki syslog check
# ---------------------------------------------------------------------------

@respx.mock
def test_meraki_syslog_check_passes_with_recent_docs():
    respx.post("https://es.example.com/logs-cisco_meraki.log-default/_count").respond(
        json={"count": 55})
    result = check_meraki_syslog_recent(CTX)
    assert "55" in result


@respx.mock
def test_meraki_syslog_check_fails_with_zero_docs():
    respx.post("https://es.example.com/logs-cisco_meraki.log-default/_count").respond(
        json={"count": 0})
    with pytest.raises(CheckFailed, match="0 docs"):
        check_meraki_syslog_recent(CTX)


@respx.mock
def test_meraki_syslog_check_fails_when_stream_missing():
    respx.post("https://es.example.com/logs-cisco_meraki.log-default/_count").respond(
        status_code=404, json={})
    with pytest.raises(CheckFailed, match="does not exist"):
        check_meraki_syslog_recent(CTX)


# ---------------------------------------------------------------------------
# Meraki webhook events check
# ---------------------------------------------------------------------------

@respx.mock
def test_meraki_events_check_passes_with_recent_docs():
    respx.post("https://es.example.com/logs-cisco_meraki.events-default/_count").respond(
        json={"count": 12})
    result = check_meraki_events_recent(CTX)
    assert "12" in result


@respx.mock
def test_meraki_events_check_fails_with_zero_docs():
    respx.post("https://es.example.com/logs-cisco_meraki.events-default/_count").respond(
        json={"count": 0})
    with pytest.raises(CheckFailed, match="0 docs"):
        check_meraki_events_recent(CTX)


@respx.mock
def test_meraki_events_check_fails_when_stream_missing():
    respx.post("https://es.example.com/logs-cisco_meraki.events-default/_count").respond(
        status_code=404, json={})
    with pytest.raises(CheckFailed, match="does not exist"):
        check_meraki_events_recent(CTX)


# ---------------------------------------------------------------------------
# PANW log-type coverage check
# ---------------------------------------------------------------------------

def _terms_agg_response(field_values: list[str]) -> dict:
    """Build a fake ES aggregation response with a single terms bucket set."""
    buckets = [{"key": v, "doc_count": 10} for v in field_values]
    return {
        "aggregations": {
            "log_types":   {"buckets": buckets},
            "event_types": {"buckets": buckets},
            "mnemonics":   {"buckets": buckets},
            "alert_types": {"buckets": buckets},
        }
    }


def _empty_agg_response() -> dict:
    """Aggregation response with zero buckets (primary field not mapped)."""
    return {"aggregations": {"alert_types": {"buckets": []}}}


@respx.mock
def test_panw_log_types_passes_with_all_three():
    respx.post("https://es.example.com/logs-panw.panos-default/_search").respond(
        json=_terms_agg_response(["TRAFFIC", "THREAT", "SYSTEM"]))
    result = check_panw_log_types(CTX)
    assert "TRAFFIC" in result or "SYSTEM" in result


@respx.mock
def test_panw_log_types_fails_when_type_missing():
    respx.post("https://es.example.com/logs-panw.panos-default/_search").respond(
        json=_terms_agg_response(["TRAFFIC", "THREAT"]))  # SYSTEM missing
    with pytest.raises(CheckFailed, match="missing"):
        check_panw_log_types(CTX)


@respx.mock
def test_panw_log_types_fails_when_stream_missing():
    respx.post("https://es.example.com/logs-panw.panos-default/_search").respond(
        status_code=404, json={})
    with pytest.raises(CheckFailed, match="does not exist"):
        check_panw_log_types(CTX)


# ---------------------------------------------------------------------------
# Meraki event variety check (pipeline-error guard + alert-type variety)
# ---------------------------------------------------------------------------

_DS_COUNT = "https://es.example.com/logs-cisco_meraki.events-default/_count"
_DS_SEARCH = "https://es.example.com/logs-cisco_meraki.events-default/_search"
_ALERT_VALUES = ["APs went down", "APs came up", "Clients connected"]


@respx.mock
def test_meraki_event_variety_passes_with_primary_field():
    """Primary field (cisco_meraki.alert_type) returns data — happy path."""
    respx.post(_DS_COUNT).respond(json={"count": 0})
    respx.post(_DS_SEARCH).respond(json=_terms_agg_response(_ALERT_VALUES))
    result = check_meraki_event_variety(CTX)
    assert "3" in result
    assert "cisco_meraki.alert_type" in result


@respx.mock
def test_meraki_event_variety_falls_back_to_json_alertType():
    """Primary field returns 0 buckets → falls back to json.alertType."""
    respx.post(_DS_COUNT).respond(json={"count": 0})
    # First _search call returns 0 buckets; second returns 3 buckets.
    # respx supports a Sequence as side_effect — responses are consumed in order.
    respx.post(_DS_SEARCH).mock(side_effect=[
        httpx.Response(200, json=_empty_agg_response()),
        httpx.Response(200, json=_terms_agg_response(_ALERT_VALUES)),
    ])
    result = check_meraki_event_variety(CTX)
    assert "3" in result
    assert "json.alertType" in result


@respx.mock
def test_meraki_event_variety_fails_on_pipeline_error_docs():
    """Any pipeline_error doc → hard fail (payload schema fix required)."""
    respx.post(_DS_COUNT).respond(json={"count": 5})
    with pytest.raises(CheckFailed, match="pipeline_error"):
        check_meraki_event_variety(CTX)


@respx.mock
def test_meraki_event_variety_fails_with_insufficient_variety():
    """Fewer than 2 distinct alert types after both field attempts → fail."""
    respx.post(_DS_COUNT).respond(json={"count": 0})
    # Both _search calls return only 1 bucket
    respx.post(_DS_SEARCH).respond(json=_terms_agg_response(["APs went down"]))
    with pytest.raises(CheckFailed, match="need >= 2"):
        check_meraki_event_variety(CTX)


@respx.mock
def test_meraki_event_variety_fails_when_stream_missing():
    """404 on _count → data stream does not exist."""
    respx.post(_DS_COUNT).respond(status_code=404, json={})
    with pytest.raises(CheckFailed, match="does not exist"):
        check_meraki_event_variety(CTX)


# ---------------------------------------------------------------------------
# IOS mnemonic variety check
# ---------------------------------------------------------------------------

@respx.mock
def test_ios_mnemonic_variety_passes_with_four_codes():
    respx.post("https://es.example.com/logs-cisco_ios.log-default/_search").respond(
        json=_terms_agg_response(["LOGIN_SUCCESS", "CONFIG_I", "UPDOWN", "LOGGINGHOST_STARTSTOP"]))
    result = check_ios_mnemonic_variety(CTX)
    assert "4" in result


@respx.mock
def test_ios_mnemonic_variety_fails_with_two_codes():
    respx.post("https://es.example.com/logs-cisco_ios.log-default/_search").respond(
        json=_terms_agg_response(["LOGIN_SUCCESS", "CONFIG_I"]))
    with pytest.raises(CheckFailed, match="need"):
        check_ios_mnemonic_variety(CTX)


@respx.mock
def test_ios_mnemonic_variety_fails_when_stream_missing():
    respx.post("https://es.example.com/logs-cisco_ios.log-default/_search").respond(
        status_code=404, json={})
    with pytest.raises(CheckFailed, match="does not exist"):
        check_ios_mnemonic_variety(CTX)
