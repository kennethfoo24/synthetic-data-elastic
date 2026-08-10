from __future__ import annotations

import httpx


class FleetSetupError(RuntimeError):
    pass


class FleetClient:
    def __init__(self, kibana_url: str, api_key: str):
        self.http = httpx.Client(
            base_url=kibana_url.rstrip("/"),
            headers={
                "Authorization": f"ApiKey {api_key}",
                "kbn-xsrf": "true",
                "Content-Type": "application/json",
            },
            timeout=60,
        )

    def _check(self, r: httpx.Response, what: str) -> httpx.Response:
        if r.status_code >= 400:
            raise FleetSetupError(f"{what} failed: HTTP {r.status_code}: {r.text[:500]}")
        return r

    def get_or_create_agent_policy(self, name: str) -> str:
        r = self._check(self.http.get("/api/fleet/agent_policies",
                                      params={"kuery": f'name:"{name}"'}), "list agent policies")
        for item in r.json().get("items", []):
            if item["name"] == name:
                return item["id"]
        r = self._check(self.http.post("/api/fleet/agent_policies", json={
            "name": name, "namespace": "default",
            "description": "Synthetic network observability (managed by synthsetup)",
            "monitoring_enabled": ["logs", "metrics"],
        }), "create agent policy")
        return r.json()["item"]["id"]

    def latest_package_version(self, pkg: str) -> str:
        r = self._check(self.http.get(f"/api/fleet/epm/packages/{pkg}"), f"get package {pkg}")
        return r.json()["item"]["version"]

    def ensure_package_policy(self, name: str, policy_id: str, package: str,
                              version: str, inputs: dict) -> None:
        body = {
            "name": name, "policy_id": policy_id,
            "package": {"name": package, "version": version},
            "inputs": inputs,
        }
        r = self.http.post("/api/fleet/package_policies", json=body)
        if r.status_code == 409:
            # Policy already exists — look it up and PUT to reconcile config changes
            r_lookup = self._check(
                self.http.get("/api/fleet/package_policies",
                              params={"kuery": f'fleet-package-policies.name:"{name}"'}),
                f"lookup package policy {name}",
            )
            items = r_lookup.json().get("items", [])
            existing = next((i for i in items if i["name"] == name), None)
            if existing is None:
                raise FleetSetupError(f"lookup package policy {name}: not found after 409")
            self._check(
                self.http.put(f"/api/fleet/package_policies/{existing['id']}", json=body),
                f"update package policy {name}",
            )
            return
        self._check(r, f"create package policy {name}")

    def get_or_create_enrollment_token(self, policy_id: str) -> str:
        r = self._check(self.http.get("/api/fleet/enrollment_api_keys"), "list enrollment keys")
        for item in r.json().get("items", []):
            if item.get("policy_id") == policy_id and item.get("active"):
                return item["api_key"]
        r = self._check(self.http.post("/api/fleet/enrollment_api_keys",
                                       json={"policy_id": policy_id}), "create enrollment key")
        return r.json()["item"]["api_key"]

    def default_fleet_url(self) -> str:
        r = self._check(self.http.get("/api/fleet/fleet_server_hosts"), "list fleet server hosts")
        items = r.json().get("items", [])
        if not items:
            raise FleetSetupError("no fleet server hosts configured on this project")
        default = next((i for i in items if i.get("is_default")), items[0])
        return default["host_urls"][0]
