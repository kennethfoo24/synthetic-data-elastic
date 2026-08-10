from __future__ import annotations

import base64
import os

from kubernetes import client as k8s
from kubernetes import config as k8s_config
from kubernetes.client.exceptions import ApiException

from synthsetup.fleet_client import FleetClient

AGENT_POLICY = "synthetic-network"
ASA_PORT = 9001

CISCO_ASA_INPUTS = {
    "cisco_asa-udp": {
        "enabled": True,
        "streams": {
            "cisco_asa.log": {
                "enabled": True,
                "vars": {"syslog_host": "0.0.0.0", "syslog_port": ASA_PORT},
            }
        },
    }
}


def write_enrollment_secret(namespace: str, fleet_url: str, token: str) -> None:
    k8s_config.load_incluster_config()
    api = k8s.CoreV1Api()
    body = k8s.V1Secret(
        metadata=k8s.V1ObjectMeta(name="agent-enrollment", namespace=namespace),
        data={
            "FLEET_URL": base64.b64encode(fleet_url.encode()).decode(),
            "FLEET_ENROLLMENT_TOKEN": base64.b64encode(token.encode()).decode(),
        },
    )
    try:
        api.create_namespaced_secret(namespace, body)
    except ApiException as exc:
        if exc.status != 409:
            raise
        api.replace_namespaced_secret("agent-enrollment", namespace, body)


def main() -> None:
    fleet = FleetClient(os.environ["KIBANA_URL"], os.environ["ELASTIC_API_KEY"])
    namespace = os.environ.get("K8S_NAMESPACE", "synthetic-network")

    policy_id = fleet.get_or_create_agent_policy(AGENT_POLICY)
    print(f"agent policy: {policy_id}", flush=True)

    version = fleet.latest_package_version("cisco_asa")
    fleet.ensure_package_policy("cisco-asa-syslog", policy_id, "cisco_asa", version,
                                CISCO_ASA_INPUTS)
    print(f"cisco_asa {version}: integration policy ensured (dashboards installed)", flush=True)

    token = fleet.get_or_create_enrollment_token(policy_id)
    fleet_url = fleet.default_fleet_url()
    write_enrollment_secret(namespace, fleet_url, token)
    print(f"enrollment secret written to {namespace}/agent-enrollment", flush=True)


if __name__ == "__main__":
    main()
