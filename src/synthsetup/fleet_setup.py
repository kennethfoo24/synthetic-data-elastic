from __future__ import annotations

import base64
import os

from kubernetes import client as k8s
from kubernetes import config as k8s_config
from kubernetes.client.exceptions import ApiException

from synthsetup.fleet_client import FleetClient

AGENT_POLICY = "synthetic-network"
ASA_PORT = 9001
IOS_PORT = 9002
PANW_PORT = 9003
NETFLOW_PORT = 2055
MERAKI_SYSLOG_PORT = 9005
MERAKI_WEBHOOK_PORT = 9004
MERAKI_WEBHOOK_SECRET = "synthetic-meraki-secret"

# devpass123: committed non-sensitive dev credential — see k8s/databases/postgres.yaml.
_PG_DEVPASS = "devpass123"

CISCO_ASA_INPUTS = {
    "cisco_asa-udp": {
        "enabled": True,
        "streams": {
            "cisco_asa.log": {
                "enabled": True,
                "vars": {"udp_host": "0.0.0.0", "udp_port": ASA_PORT},
            }
        },
    }
}

CISCO_IOS_INPUTS = {
    "cisco_ios-udp": {
        "enabled": True,
        "streams": {
            "cisco_ios.log": {
                "enabled": True,
                "vars": {"syslog_host": "0.0.0.0", "syslog_port": IOS_PORT},
            }
        },
    }
}

PANW_INPUTS = {
    "panw-udp": {
        "enabled": True,
        "streams": {
            "panw.panos": {
                "enabled": True,
                "vars": {
                    "syslog_host": "0.0.0.0",
                    "syslog_port": PANW_PORT,
                    "internal_zones": ["inside"],
                    "external_zones": ["outside"],
                },
            }
        },
    }
}

NETFLOW_INPUTS = {
    "netflow-netflow": {
        "enabled": True,
        "streams": {
            "netflow.log": {
                "enabled": True,
                "vars": {
                    "host": "0.0.0.0",
                    "port": NETFLOW_PORT,
                    "internal_networks": ["private"],
                },
            }
        },
    }
}

# cisco_meraki 1.31.1 has no cloud-API polling input — syslog (UDP) for
# cisco_meraki.log and webhook (HTTP endpoint/TCP) for cisco_meraki.events.
CISCO_MERAKI_INPUTS = {
    "cisco_meraki-udp": {
        "enabled": True,
        "streams": {
            "cisco_meraki.log": {
                "enabled": True,
                "vars": {
                    "listen_address": "0.0.0.0",
                    "listen_port": MERAKI_SYSLOG_PORT,
                },
            }
        },
    },
    "cisco_meraki-http_endpoint": {
        "enabled": True,
        "streams": {
            "cisco_meraki.events": {
                "enabled": True,
                "vars": {
                    "listen_address": "0.0.0.0",
                    "listen_port": MERAKI_WEBHOOK_PORT,
                    "url": "/meraki/events",
                    "secret_value": MERAKI_WEBHOOK_SECRET,
                },
            }
        },
    },
}

# MongoDB replica set: both members listed so Fleet scrapes metrics from
# both the primary (mongodb-prod) and the secondary (mongodb-dr).
# replstatus stream is enabled to expose replication lag metrics.
# Log collection (mongodb.log) is out of scope for Plan 2 — container-log
# shipping via a non-DaemonSet agent is impractical; recorded as a gap for
# the K8s-integration follow-up plan.
MONGODB_INPUTS = {
    "mongodb-mongodb/metrics": {
        "enabled": True,
        "vars": {
            # mongodb-prod uses the replica-set URI so Fleet follows topology.
            # mongodb-dr uses directConnection=true so Fleet bypasses topology
            # discovery and scrapes the secondary directly — without it the driver
            # always routes to the primary, making both entries report identical
            # primary metrics and replstatus is useless for lag detection.
            "hosts": [
                "mongodb-prod:27017",
                "mongodb://mongodb-dr:27017/?directConnection=true",
            ],
        },
        "streams": {
            "mongodb.collstats": {"enabled": True, "vars": {"period": "10s"}},
            "mongodb.dbstats": {"enabled": True, "vars": {"period": "10s"}},
            "mongodb.metrics": {"enabled": True, "vars": {"period": "10s"}},
            "mongodb.replstatus": {"enabled": True, "vars": {"period": "10s"}},
            "mongodb.status": {"enabled": True, "vars": {"period": "10s"}},
        },
    }
}

# PostgreSQL primary only for metrics (Fleet agent reads from the primary).
# hosts format is host:port (separate username/password vars per pkg schema).
# pg_stat_statements must be loaded on the server (done via -c arg in the
# StatefulSet manifest) for postgresql.statement metrics to work.
# Log collection (postgresql.log) is out of scope for Plan 2 — same gap as
# MongoDB: container-log shipping requires a DaemonSet-based agent.
POSTGRESQL_INPUTS = {
    "postgresql-postgresql/metrics": {
        "enabled": True,
        "vars": {
            "hosts": ["postgres-prod:5432"],
            "username": "postgres",
            "password": _PG_DEVPASS,
        },
        "streams": {
            "postgresql.activity": {"enabled": True, "vars": {"period": "10s"}},
            "postgresql.bgwriter": {"enabled": True, "vars": {"period": "10s"}},
            "postgresql.database": {"enabled": True, "vars": {"period": "10s"}},
            "postgresql.statement": {"enabled": True, "vars": {"period": "10s"}},
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

    version = fleet.latest_package_version("cisco_ios")
    fleet.ensure_package_policy("cisco-ios-syslog", policy_id, "cisco_ios", version,
                                CISCO_IOS_INPUTS)
    print(f"cisco_ios {version}: integration policy ensured", flush=True)

    version = fleet.latest_package_version("panw")
    fleet.ensure_package_policy("panw-syslog", policy_id, "panw", version, PANW_INPUTS)
    print(f"panw {version}: integration policy ensured", flush=True)

    version = fleet.latest_package_version("netflow")
    fleet.ensure_package_policy("netflow-netflow", policy_id, "netflow", version, NETFLOW_INPUTS)
    print(f"netflow {version}: integration policy ensured (port {NETFLOW_PORT}/UDP)", flush=True)

    version = fleet.latest_package_version("mongodb")
    fleet.ensure_package_policy("mongodb-metrics", policy_id, "mongodb", version,
                                MONGODB_INPUTS)
    print(f"mongodb {version}: integration policy ensured (replstatus enabled)", flush=True)

    version = fleet.latest_package_version("postgresql")
    fleet.ensure_package_policy("postgresql-metrics", policy_id, "postgresql", version,
                                POSTGRESQL_INPUTS)
    print(f"postgresql {version}: integration policy ensured (pg_stat_statements)", flush=True)

    version = fleet.latest_package_version("cisco_meraki")
    fleet.ensure_package_policy("cisco-meraki", policy_id, "cisco_meraki", version,
                                CISCO_MERAKI_INPUTS)
    print(
        f"cisco_meraki {version}: integration policy ensured "
        f"(syslog port {MERAKI_SYSLOG_PORT}/UDP, webhook port {MERAKI_WEBHOOK_PORT}/TCP)",
        flush=True,
    )

    token = fleet.get_or_create_enrollment_token(policy_id)
    fleet_url = fleet.default_fleet_url()
    write_enrollment_secret(namespace, fleet_url, token)
    print(f"enrollment secret written to {namespace}/agent-enrollment", flush=True)


if __name__ == "__main__":
    main()
