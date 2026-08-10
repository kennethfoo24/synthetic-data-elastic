import pytest
import respx

from synthsetup.validate import (
    CheckFailed,
    Ctx,
    check_agents_online,
    check_asa_docs_recent,
    check_ios_docs_recent,
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
