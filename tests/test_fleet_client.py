import respx

from synthsetup.fleet_client import FleetClient

KB = "https://kb.example.com"

def client() -> FleetClient:
    return FleetClient(KB, "fake-key")

@respx.mock
def test_creates_policy_when_absent():
    respx.get(f"{KB}/api/fleet/agent_policies").respond(json={"items": []})
    route = respx.post(f"{KB}/api/fleet/agent_policies").respond(
        json={"item": {"id": "pol-1", "name": "synthetic-network"}})
    assert client().get_or_create_agent_policy("synthetic-network") == "pol-1"
    body = route.calls.last.request.content
    assert b"synthetic-network" in body

@respx.mock
def test_reuses_existing_policy():
    respx.get(f"{KB}/api/fleet/agent_policies").respond(
        json={"items": [{"id": "pol-9", "name": "synthetic-network"}]})
    assert client().get_or_create_agent_policy("synthetic-network") == "pol-9"

@respx.mock
def test_package_policy_409_is_success():
    respx.get(f"{KB}/api/fleet/epm/packages/cisco_asa").respond(
        json={"item": {"version": "2.34.0"}})
    respx.post(f"{KB}/api/fleet/package_policies").respond(409, json={"message": "exists"})
    c = client()
    v = c.latest_package_version("cisco_asa")
    c.ensure_package_policy("cisco-asa-syslog", "pol-1", "cisco_asa", v, inputs={})

@respx.mock
def test_enrollment_token():
    respx.get(f"{KB}/api/fleet/enrollment_api_keys").respond(
        json={"items": [{"policy_id": "pol-1", "api_key": "tok==", "active": True}]})
    assert client().get_or_create_enrollment_token("pol-1") == "tok=="

@respx.mock
def test_auth_headers_sent():
    route = respx.get(f"{KB}/api/fleet/agent_policies").respond(json={"items": []})
    respx.post(f"{KB}/api/fleet/agent_policies").respond(json={"item": {"id": "p"}})
    client().get_or_create_agent_policy("x")
    req = route.calls.last.request
    assert req.headers["authorization"] == "ApiKey fake-key"
    assert req.headers["kbn-xsrf"] == "true"
