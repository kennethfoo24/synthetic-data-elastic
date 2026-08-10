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

echo "==> pipeline simulate gate"
.venv/bin/python -m synthsetup.simulate || { echo "ERROR: wire formats failed pipeline simulation"; exit 1; }

echo "==> namespace + credentials"
kubectl apply -f k8s/namespace.yaml
kubectl -n synthetic-network create secret generic elastic-credentials \
  --from-literal=ES_URL="$ES_URL" \
  --from-literal=KIBANA_URL="$KIBANA_URL" \
  --from-literal=ELASTIC_API_KEY="$ELASTIC_API_KEY" \
  --dry-run=client -o yaml | kubectl apply -f -

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
sed "s|synthetic-netgen:latest|synthetic-netgen:$IMAGE_TAG|" k8s/generators/syslog-gen.yaml | kubectl apply -f -
sed "s|synthetic-netgen:latest|synthetic-netgen:$IMAGE_TAG|" k8s/generators/syslog-ios-gen.yaml | kubectl apply -f -
sed "s|synthetic-netgen:latest|synthetic-netgen:$IMAGE_TAG|" k8s/generators/syslog-panw-gen.yaml | kubectl apply -f -
kubectl -n synthetic-network rollout status deploy/elastic-agent --timeout=300s
kubectl -n synthetic-network rollout status deploy/syslog-gen --timeout=120s
kubectl -n synthetic-network rollout status deploy/syslog-ios-gen --timeout=120s
kubectl -n synthetic-network rollout status deploy/syslog-panw-gen --timeout=120s

echo "==> done. Run 'make validate' in ~2 minutes to confirm data is flowing."
