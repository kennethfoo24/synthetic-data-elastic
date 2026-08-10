#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

[ -f .env ] || { echo "ERROR: .env missing (copy .env.example)"; exit 1; }
set -a; source .env; set +a
for v in ES_URL KIBANA_URL ELASTIC_API_KEY; do
  [ -n "${!v:-}" ] || { echo "ERROR: $v not set in .env"; exit 1; }
done

IMAGE_TAG=$(git rev-parse HEAD)
if [ -n "$(git status --porcelain)" ]; then
  echo "ERROR: working tree is dirty — commit or stash changes — deploys pin the HEAD image tag"
  exit 1
fi
docker manifest inspect "kennethfoo24/synthetic-netgen:$IMAGE_TAG" >/dev/null 2>&1 || {
  echo "ERROR: image tag $IMAGE_TAG not on Docker Hub yet — wait for CI (gh run watch)"
  exit 1
}
echo "==> pinning image kennethfoo24/synthetic-netgen:$IMAGE_TAG"

[ -d .venv ] || { echo "ERROR: .venv not found — run 'make bootstrap' first"; exit 1; }

echo "==> pipeline simulate gate"
.venv/bin/python -m synthsetup.simulate || { echo "ERROR: wire formats failed pipeline simulation"; exit 1; }

echo "==> namespace + credentials"
kubectl apply -f k8s/namespace.yaml
kubectl -n synthetic-network create secret generic elastic-credentials \
  --from-literal=ES_URL="$ES_URL" \
  --from-literal=KIBANA_URL="$KIBANA_URL" \
  --from-literal=ELASTIC_API_KEY="$ELASTIC_API_KEY" \
  --dry-run=client -o yaml | kubectl apply -f -

echo "==> databases (MongoDB replica set + PostgreSQL streaming standby)"
# Apply database manifests BEFORE the fleet-setup job so that the integration
# targets (mongodb-prod, postgres-prod) are reachable when Fleet polls them.
# Delete any stale mongodb-init Job first — a Job's pod template is immutable,
# so a leftover Job from a failed prior run causes "field is immutable" on apply.
kubectl -n synthetic-network delete job mongodb-init --ignore-not-found
kubectl apply -f k8s/databases/mongodb.yaml
kubectl apply -f k8s/databases/postgres.yaml
kubectl -n synthetic-network rollout status statefulset/mongodb-prod --timeout=120s
kubectl -n synthetic-network rollout status statefulset/mongodb-dr  --timeout=120s
kubectl -n synthetic-network rollout status statefulset/postgres-prod --timeout=180s
# postgres-dr waits for the initContainer (pg_basebackup) before the pod is Ready
kubectl -n synthetic-network rollout status statefulset/postgres-dr --timeout=300s
# Initialise the MongoDB replica set (idempotent; safe to re-apply)
kubectl -n synthetic-network delete job mongodb-init --ignore-not-found
kubectl apply -f k8s/databases/mongodb.yaml
kubectl -n synthetic-network wait --for=condition=complete job/mongodb-init --timeout=120s || {
  echo "ERROR: mongodb-init failed; logs:"; kubectl -n synthetic-network logs job/mongodb-init; exit 1;
}

echo "==> Logstash SNMP pipeline (standalone — no Fleet dependency)"
# Logstash uses the official Elastic image (already pinned to 9.1.3 in the manifest);
# applied here before fleet-setup since it has no Fleet dependency.
# snmpsim (the SNMP simulator) uses the synthetic-netgen image and is SHA-pinned
# via the generators loop below.
kubectl apply -f k8s/logstash/logstash.yaml

echo "==> fleet setup job"
kubectl apply -f k8s/rbac.yaml
kubectl -n synthetic-network delete job fleet-setup --ignore-not-found
sed "s|synthetic-netgen:latest|synthetic-netgen:$IMAGE_TAG|" k8s/jobs/fleet-setup.yaml | kubectl apply -f -
kubectl -n synthetic-network wait --for=condition=complete job/fleet-setup --timeout=300s || {
  echo "ERROR: fleet-setup failed; logs:"; kubectl -n synthetic-network logs job/fleet-setup; exit 1;
}
kubectl -n synthetic-network logs job/fleet-setup

echo "==> agent + generators"
kubectl apply -f k8s/elastic-agent.yaml
# SHA-pin every synthetic-netgen reference: loop over all generator manifests
# (includes snmpsim which uses synthetic-netgen with the [snmp] extras).
# logstash uses the official Elastic image and was applied plain above.
for manifest in k8s/generators/*.yaml; do
  sed "s|synthetic-netgen:latest|synthetic-netgen:$IMAGE_TAG|" "$manifest" | kubectl apply -f -
done

echo "==> rollout waits"
kubectl -n synthetic-network rollout status deploy/elastic-agent --timeout=300s
for manifest in k8s/generators/*.yaml; do
  name=$(basename "$manifest" .yaml)
  kubectl -n synthetic-network rollout status "deploy/$name" --timeout=120s
done
kubectl -n synthetic-network rollout status deploy/logstash --timeout=300s

echo "==> done. Run 'make validate' in ~2 minutes to confirm data is flowing."
