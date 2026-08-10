.PHONY: up down validate test

up:
	./deploy.sh

down:
	kubectl delete namespace synthetic-network --ignore-not-found

validate:
	set -a; . ./.env; set +a; .venv/bin/python -m synthsetup.validate

test:
	.venv/bin/ruff check . && .venv/bin/pytest -v
