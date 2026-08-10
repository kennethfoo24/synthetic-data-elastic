import json

import pytest
import respx

from synthsetup.fleet_client import FleetClient, FleetSetupError
from synthsetup.fleet_setup import (
    CISCO_ASA_INPUTS,
    CISCO_IOS_INPUTS,
    CISCO_MERAKI_INPUTS,
    PANW_INPUTS,
    POSTGRESQL_INPUTS,
)

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
def test_package_policy_409_reconciles():
    """On 409, look up existing policy and PUT to reconcile config changes."""
    respx.get(f"{KB}/api/fleet/epm/packages/cisco_asa").respond(
        json={"item": {"version": "2.34.0"}})
    respx.post(f"{KB}/api/fleet/package_policies").respond(409, json={"message": "exists"})
    respx.get(f"{KB}/api/fleet/package_policies").respond(
        json={"items": [{"id": "pp-99", "name": "cisco-asa-syslog"}]})
    put_route = respx.put(f"{KB}/api/fleet/package_policies/pp-99").respond(
        json={"item": {"id": "pp-99"}})
    c = client()
    v = c.latest_package_version("cisco_asa")
    c.ensure_package_policy("cisco-asa-syslog", "pol-1", "cisco_asa", v, inputs={})
    assert put_route.called
    # Verify PUT body contains expected fields
    import json
    from urllib.parse import parse_qs, urlparse
    put_body = json.loads(put_route.calls.last.request.content)
    assert put_body["name"] == "cisco-asa-syslog"
    assert put_body["policy_id"] == "pol-1"
    assert put_body["package"]["name"] == "cisco_asa"
    # Verify GET lookup used the prefixed kuery form required by the Fleet API
    get_calls = [c for c in respx.calls if c.request.method == "GET"
                 and "/api/fleet/package_policies" in str(c.request.url)]
    assert get_calls, "expected a GET /api/fleet/package_policies lookup call"
    qs = parse_qs(urlparse(str(get_calls[0].request.url)).query)
    assert qs.get("kuery") == ['fleet-package-policies.name:"cisco-asa-syslog"']

@respx.mock
def test_package_policy_409_put_failure_raises():
    """On 409, if PUT to update existing policy fails, raise FleetSetupError."""
    from urllib.parse import parse_qs, urlparse
    respx.get(f"{KB}/api/fleet/epm/packages/cisco_asa").respond(
        json={"item": {"version": "2.34.0"}})
    respx.post(f"{KB}/api/fleet/package_policies").respond(409, json={"message": "exists"})
    respx.get(f"{KB}/api/fleet/package_policies").respond(
        json={"items": [{"id": "pp-99", "name": "cisco-asa-syslog"}]})
    respx.put(f"{KB}/api/fleet/package_policies/pp-99").respond(500, json={"message": "server error"})
    c = client()
    v = c.latest_package_version("cisco_asa")
    with pytest.raises(FleetSetupError, match="update package policy cisco-asa-syslog"):
        c.ensure_package_policy("cisco-asa-syslog", "pol-1", "cisco_asa", v, inputs={})
    # Verify the prefixed kuery was used in the lookup
    get_calls = [c for c in respx.calls if c.request.method == "GET"
                 and "/api/fleet/package_policies" in str(c.request.url)]
    qs = parse_qs(urlparse(str(get_calls[0].request.url)).query)
    assert qs.get("kuery") == ['fleet-package-policies.name:"cisco-asa-syslog"']

@respx.mock
def test_package_policy_409_lookup_not_found_raises():
    """On 409, if GET lookup returns no matching policy, raise FleetSetupError."""
    from urllib.parse import parse_qs, urlparse
    respx.get(f"{KB}/api/fleet/epm/packages/cisco_asa").respond(
        json={"item": {"version": "2.34.0"}})
    respx.post(f"{KB}/api/fleet/package_policies").respond(409, json={"message": "exists"})
    # Lookup returns empty list (or items with no name match)
    respx.get(f"{KB}/api/fleet/package_policies").respond(json={"items": []})
    c = client()
    v = c.latest_package_version("cisco_asa")
    with pytest.raises(FleetSetupError, match="lookup package policy cisco-asa-syslog"):
        c.ensure_package_policy("cisco-asa-syslog", "pol-1", "cisco_asa", v, inputs={})
    # Verify the prefixed kuery was used in the lookup
    get_calls = [c for c in respx.calls if c.request.method == "GET"
                 and "/api/fleet/package_policies" in str(c.request.url)]
    qs = parse_qs(urlparse(str(get_calls[0].request.url)).query)
    assert qs.get("kuery") == ['fleet-package-policies.name:"cisco-asa-syslog"']

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


@respx.mock
def test_disabled_tcp_logfile_inputs_sent_in_post_body():
    """Unused TCP/logfile inputs must be explicitly disabled in the Fleet POST body.

    When multiple syslog packages are installed in the same agent policy, each
    package enables a default TCP listener on the same port (127.0.0.1:9001).
    Sending enabled=False for those inputs prevents the port-collision FAILED
    component state that causes the agent to report DEGRADED.
    """
    respx.get(f"{KB}/api/fleet/epm/packages/cisco_asa").respond(
        json={"item": {"version": "2.34.0"}})
    post_route = respx.post(f"{KB}/api/fleet/package_policies").respond(
        json={"item": {"id": "pp-1"}})
    c = client()
    v = c.latest_package_version("cisco_asa")
    c.ensure_package_policy("cisco-asa-syslog", "pol-1", "cisco_asa", v, CISCO_ASA_INPUTS)

    body = json.loads(post_route.calls.last.request.content)
    inputs = body["inputs"]
    # TCP input must be present and disabled
    assert "cisco_asa-tcp" in inputs, "cisco_asa-tcp not in POST body inputs"
    assert inputs["cisco_asa-tcp"]["enabled"] is False, "cisco_asa-tcp should be disabled"
    # Logfile input must be present and disabled
    assert "cisco_asa-logfile" in inputs, "cisco_asa-logfile not in POST body inputs"
    assert inputs["cisco_asa-logfile"]["enabled"] is False, "cisco_asa-logfile should be disabled"
    # UDP input must still be enabled
    assert inputs["cisco_asa-udp"]["enabled"] is True


@pytest.mark.parametrize("pkg_inputs,tcp_key,logfile_key", [
    (CISCO_IOS_INPUTS, "cisco_ios-tcp", "cisco_ios-logfile"),
    (PANW_INPUTS, "panw-tcp", "panw-logfile"),
    (CISCO_MERAKI_INPUTS, "cisco_meraki-tcp", "cisco_meraki-logfile"),
])
def test_all_syslog_packages_disable_tcp_logfile(pkg_inputs, tcp_key, logfile_key):
    """All syslog packages must carry disabled tcp/logfile keys to prevent collision."""
    assert tcp_key in pkg_inputs, f"{tcp_key} missing from inputs dict"
    assert pkg_inputs[tcp_key]["enabled"] is False, f"{tcp_key} should be disabled"
    assert logfile_key in pkg_inputs, f"{logfile_key} missing from inputs dict"
    assert pkg_inputs[logfile_key]["enabled"] is False, f"{logfile_key} should be disabled"


def test_postgresql_hosts_use_dsn_with_sslmode_disable():
    """PostgreSQL hosts must use full DSN form with sslmode=disable.

    The in-cluster PostgreSQL StatefulSet does not have SSL configured.
    Without sslmode=disable the driver attempts SSL negotiation and the
    postgresql.activity stream fails with "pq: SSL is not enabled".
    """
    vars_ = POSTGRESQL_INPUTS["postgresql-postgresql/metrics"]["vars"]
    hosts = vars_["hosts"]
    assert len(hosts) == 1, "expected exactly one PostgreSQL host"
    host = hosts[0]
    assert host.startswith("postgres://"), (
        f"hosts entry must be a DSN (postgres://...), got: {host!r}"
    )
    assert "sslmode=disable" in host, (
        f"hosts DSN must include sslmode=disable, got: {host!r}"
    )
