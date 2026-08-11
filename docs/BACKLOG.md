# Backlog

## Plan 4 completed (2026-08-11)

24 recurring failure scenarios across 8 telemetry sources, a 7-day idempotent backfill, and 3 custom Kibana dashboards are complete and live-verified:

- **24 scenarios** (`src/synthgen/common/scenarios.py`): 3 per source for panw, asa, ios, meraki, mongodb, postgresql, hpe, dell — each fires every 3h ± 45 min with concrete field-level effects documented in `docs/scenarios/`
- **7-day backfill** (`src/synthsetup/backfill.py`): idempotent, covers all streams (syslog, NetFlow, SNMP); run with `make backfill`
- **3 custom dashboards** (`setup/dashboards/{hpe,dell,network-overview}.ndjson`): import with `make import-dashboards`; IDs `synthnet-hpe-infrastructure`, `synthnet-dell-infrastructure`, `synthnet-network-overview`

---

Carried findings from Plan 1's final whole-branch review (2026-08-10). None block Plan 1; triage into Plans 2–4.

## Plan 2 entry work (will bite immediately if skipped)

- **Fleet reconcile-on-exists:** `ensure_package_policy` treats HTTP 409 as success and never updates an existing integration policy. Any change to integration config (or a package version bump) silently no-ops on redeploy. Add update-by-name on 409.
- **deploy.sh image guard:** `IMAGE_TAG=$(git rev-parse HEAD)` assumes the SHA-tagged image exists on Docker Hub. Guard with a dirty-tree/unpushed check or `docker manifest inspect` before deploying, else the fleet-setup Job hangs 300s with an empty diagnostic.

## Plan 2 general

- Wire the flow matrix into generators — `asa_source.py` invents traffic instead of deriving from `topology/network.yaml` flows (NetFlow generator will consume flows; align ASA conn logs then too).
- Disable the unused `cisco_asa-tcp` input in the integration policy (agent currently opens a dead TCP listener).
- Align AAA server IP in `formats/asa.py` (10.20.7.5) with a real topology device.
- `validate.py`: surface 401/403 as auth errors instead of "0 docs"; test the 404 branch.
- Multi-replica hazard: generator PRNG is keyed on timestamp only — 2 replicas emit identical logs. Key on pod identity if scaling.
- `conftest.py` to anchor pytest cwd; Makefile bootstrap target for `.venv`.
- Resolve the two deploy paths: `kubectl apply -k k8s/` (CI-validated) deploys `:latest` and skips secrets — either fix kustomization images or remove it.
- README: remove stale "Coming in later tasks", document `.venv` bootstrap.

## Hardening (any plan)

- RBAC: add `resourceNames: [agent-enrollment]` to the fleet-setup Role; drop fake `replace` verb.
- Workflows: add least-privilege `permissions:` blocks.
- Dockerfile: non-root user, pin base image digest; add `.env` to `.dockerignore`.
- Ruff: add a `select` list (current config only runs E4/E7/E9/F; existing `noqa` comments reference disabled rules).

## Plan 3

- Geolocatable public source IPs (203.0.113.x can't be placed by GeoIP → geo panels empty).
- `keep_message` var if sample-message columns should populate.

## Plan 2 carried gaps

- **MongoDB log collection (mongodb.log):** The `mongodb/metrics` integration is in place, but `mongodb.log` log collection requires the `logfile` input with a pod-specific container log path. A non-DaemonSet Elastic Agent (single Deployment) cannot access log files on arbitrary nodes. Revisit with the K8s-integration follow-up (DaemonSet agent or log-shipping sidecar per DB pod).
- **PostgreSQL log collection (postgresql.log):** Same limitation as MongoDB. The `logfile` input in the `postgresql` package needs a path to the container's PostgreSQL log file, which is not accessible from a Deployment-scoped agent. Resolution: DaemonSet agent or Filebeat sidecar — deferred to K8s-integration plan.
- **Meraki cloud-API polling:** `cisco_meraki` has no API-polling input (verified 1.31.1) — webhook + syslog only; revisit if a Meraki API integration ships.

## Deferred minors from task reviews

- FleetClient/Ctx httpx.Client never closed (harmless in short-lived processes).
- IndexError on empty `host_urls` (theoretical).
- Loader duplicates flow-endpoint check; `sites` block unused (Plan 2 consumes subnets).
- Progress-print in `__main__.py` can emit up to 10 consecutive lines per 500 msgs.
