import respx

from synthsetup.validate import Ctx, check_agents_online, check_asa_docs_recent

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
    respx.get("https://kb.example.com/api/fleet/agents").respond(
        json={"items": [{"status": "online", "policy_id": "p"}], "total": 1})
    assert "online" in check_agents_online(CTX)
