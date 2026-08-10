.PHONY: up down validate test bootstrap reset-databases

bootstrap:
	python3.12 -m venv .venv && .venv/bin/pip install -e '.[dev]'

up:
	./deploy.sh

down:
	kubectl delete namespace synthetic-network --ignore-not-found

validate:
	set -a; . ./.env; set +a; .venv/bin/python -m synthsetup.validate

test:
	.venv/bin/ruff check . && .venv/bin/pytest -v

# reset-databases: recover after a primary pod restart has left the replica
# set / standby in an inconsistent state (emptyDir-backed DBs do not survive
# pod restarts — see headers in k8s/databases/*.yaml for details).
#
# Steps:
#   1. Delete both DB pods so their emptyDir volumes are cleared.
#   2. Delete the mongodb-init Job so it can be recreated.
#   3. Wait for StatefulSets to bring up fresh pods (readiness probes gate this).
#   4. Re-apply the database manifests (re-creates mongodb-init Job).
#   5. Wait for mongodb-init to complete (idempotent: skips if already done).
reset-databases:
	@echo "==> Resetting DB pods (emptyDir cleared on restart — expected for lab)"
	kubectl -n synthetic-network delete pod mongodb-prod-0 mongodb-dr-0 \
	  postgres-prod-0 postgres-dr-0 --ignore-not-found
	kubectl -n synthetic-network delete job mongodb-init --ignore-not-found
	@echo "==> Waiting for StatefulSets to bring up fresh pods..."
	kubectl -n synthetic-network rollout status statefulset/mongodb-prod --timeout=120s
	kubectl -n synthetic-network rollout status statefulset/mongodb-dr  --timeout=120s
	kubectl -n synthetic-network rollout status statefulset/postgres-prod --timeout=180s
	kubectl -n synthetic-network rollout status statefulset/postgres-dr  --timeout=300s
	@echo "==> Re-applying database manifests (recreates mongodb-init Job)..."
	kubectl apply -f k8s/databases/mongodb.yaml
	kubectl apply -f k8s/databases/postgres.yaml
	kubectl -n synthetic-network wait --for=condition=complete \
	  job/mongodb-init --timeout=120s || { \
	  echo "ERROR: mongodb-init failed; logs:"; \
	  kubectl -n synthetic-network logs job/mongodb-init; exit 1; \
	}
	@echo "==> Database bootstrap complete."
