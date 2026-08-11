"""Port-coherence tests.

Asserts that:
(a) Every enabled listener input's port is unique across all packages.
(b) Every -tcp / -logfile input entry is exactly {"enabled": False}.
(c) The set of enabled listener ports matches the containerPorts declared in
    k8s/elastic-agent.yaml (parsed as multi-doc YAML).
(d) Each generator's --target-port arg matches the corresponding fleet_setup.py
    port constant.

Pure file-parsing tests — no network calls.
"""
from __future__ import annotations

from pathlib import Path

import yaml

from synthsetup.fleet_setup import (
    ASA_PORT,
    CISCO_ASA_INPUTS,
    CISCO_IOS_INPUTS,
    CISCO_MERAKI_INPUTS,
    IOS_PORT,
    MERAKI_SYSLOG_PORT,
    MERAKI_WEBHOOK_PORT,
    NETFLOW_INPUTS,
    NETFLOW_PORT,
    PANW_INPUTS,
    PANW_PORT,
)

_REPO_ROOT = Path(__file__).parents[1]
_ELASTIC_AGENT_YAML = _REPO_ROOT / "k8s" / "elastic-agent.yaml"
_GENERATORS_DIR = _REPO_ROOT / "k8s" / "generators"

# All input dicts that carry listener ports (db-metrics inputs have no listener port)
_ALL_LISTENER_INPUTS: dict[str, dict] = {
    **CISCO_ASA_INPUTS,
    **CISCO_IOS_INPUTS,
    **PANW_INPUTS,
    **NETFLOW_INPUTS,
    **CISCO_MERAKI_INPUTS,
}


def _get_port_from_input(inp: dict) -> int | None:
    """Extract the listener port from an enabled fleet input dict.

    Searches vars for any of the known port-key names used across integrations:
    udp_port (cisco_asa), syslog_port (cisco_ios, panw), port (netflow),
    listen_port (cisco_meraki udp + http_endpoint).
    """
    if not inp.get("enabled"):
        return None
    for stream in inp.get("streams", {}).values():
        vars_ = stream.get("vars", {})
        for key in ("udp_port", "syslog_port", "port", "listen_port"):
            if key in vars_:
                return int(vars_[key])
    return None


def _enabled_listener_ports() -> dict[str, int]:
    """Return {input_name: port} for every enabled listener input."""
    return {
        name: port
        for name, inp in _ALL_LISTENER_INPUTS.items()
        if (port := _get_port_from_input(inp)) is not None
    }


# ---------------------------------------------------------------------------
# (a) Unique ports
# ---------------------------------------------------------------------------

def test_enabled_ports_are_unique():
    """Every enabled listener input must bind a unique port."""
    ports = _enabled_listener_ports()
    values = list(ports.values())
    assert len(values) == len(set(values)), (
        f"Duplicate ports detected across enabled listener inputs: {ports}"
    )


# ---------------------------------------------------------------------------
# (b) tcp/logfile inputs disabled
# ---------------------------------------------------------------------------

def test_tcp_logfile_inputs_are_disabled():
    """Every -tcp and -logfile input entry must be exactly {\"enabled\": False}."""
    for name, inp in _ALL_LISTENER_INPUTS.items():
        if "-tcp" in name or "-logfile" in name:
            assert inp == {"enabled": False}, (
                f"Input {name!r} must be exactly {{\"enabled\": False}}, got: {inp!r}"
            )


# ---------------------------------------------------------------------------
# (c) Ports match elastic-agent.yaml
# ---------------------------------------------------------------------------

def _elastic_agent_ports() -> set[int]:
    """Parse containerPorts and Service port entries from k8s/elastic-agent.yaml (multi-doc)."""
    ports: set[int] = set()
    docs = list(yaml.safe_load_all(_ELASTIC_AGENT_YAML.read_text()))
    for doc in docs:
        if doc is None:
            continue
        kind = doc.get("kind", "")
        # Deployment containerPorts
        if kind == "Deployment":
            containers = (
                doc.get("spec", {})
                   .get("template", {})
                   .get("spec", {})
                   .get("containers", [])
            )
            for container in containers:
                for port_entry in container.get("ports", []):
                    ports.add(int(port_entry["containerPort"]))
        # Service targetPort / port
        if kind == "Service":
            for svc_port in doc.get("spec", {}).get("ports", []):
                val = svc_port.get("targetPort") or svc_port.get("port")
                if val is not None:
                    ports.add(int(val))
    return ports


def test_enabled_ports_match_k8s_agent():
    """Set of enabled listener ports must equal containerPorts in k8s/elastic-agent.yaml."""
    fleet_ports = set(_enabled_listener_ports().values())
    k8s_ports = _elastic_agent_ports()
    assert fleet_ports == k8s_ports, (
        f"Port mismatch:\n"
        f"  fleet_setup.py enabled ports : {sorted(fleet_ports)}\n"
        f"  elastic-agent.yaml ports     : {sorted(k8s_ports)}"
    )


# ---------------------------------------------------------------------------
# (d) Generator --target-port args
# ---------------------------------------------------------------------------

def _generator_target_ports() -> dict[str, int]:
    """Parse --target-port=N from each generator Deployment YAML."""
    result: dict[str, int] = {}
    for yaml_path in sorted(_GENERATORS_DIR.glob("*.yaml")):
        docs = list(yaml.safe_load_all(yaml_path.read_text()))
        for doc in docs:
            if doc is None or doc.get("kind") != "Deployment":
                continue
            containers = (
                doc.get("spec", {})
                   .get("template", {})
                   .get("spec", {})
                   .get("containers", [])
            )
            for container in containers:
                for arg in container.get("args", []):
                    if isinstance(arg, str) and arg.startswith("--target-port="):
                        result[yaml_path.stem] = int(arg.split("=", 1)[1])
    return result


def test_generator_target_ports_match_fleet_setup():
    """Each generator's --target-port must match the fleet_setup.py port constant."""
    expected = {
        "syslog-gen": ASA_PORT,
        "syslog-ios-gen": IOS_PORT,
        "syslog-panw-gen": PANW_PORT,
        "syslog-meraki-gen": MERAKI_SYSLOG_PORT,
        "netflow-gen": NETFLOW_PORT,
        "meraki-webhook-gen": MERAKI_WEBHOOK_PORT,
    }
    actual = _generator_target_ports()
    for name, expected_port in expected.items():
        assert name in actual, (
            f"Generator {name!r} not found or has no --target-port in k8s/generators/*.yaml"
        )
        assert actual[name] == expected_port, (
            f"Generator {name!r}: --target-port={actual[name]} but "
            f"fleet_setup.py declares port {expected_port}"
        )
