VENV := .venv
PY := $(VENV)/bin/python
PIP := $(VENV)/bin/pip
UV := $(VENV)/bin/uvicorn
PYTEST := $(VENV)/bin/pytest
BLACK := $(VENV)/bin/black
RUFF := $(VENV)/bin/ruff
MYPY := $(VENV)/bin/mypy
BANDIT := $(VENV)/bin/bandit
ALEMBIC := $(VENV)/bin/alembic
COMPOSE ?= docker compose
API_PORT ?= 8000
FLY_APP ?= forgotten-app
FLY_DOMAIN ?= $(FLY_APP).fly.dev

.PHONY: deps run test testcov fmt lint type sec precommit \
        revision upgrade downgrade migrate up down logs dev smoke \
        smoke-fly \
        admin-credentials worker \
        test-integration

deps:
	@[ -d $(VENV) ] || python -m venv $(VENV)
	@$(PIP) -q install --upgrade pip
	@$(PIP) -q install -e ".[dev]"
	@$(VENV)/bin/pre-commit install

run: deps
	$(UV) PYTHONPATH=src app.main:app --host 0.0.0.0 --port 8000 --reload

fmt:
	$(BLACK) src tests
	$(RUFF) check --fix src tests

lint:
	$(RUFF) check src tests
	$(BLACK) --check src tests

type:
	$(MYPY) src

sec:
	$(BANDIT) -q -r src || true

test:
	$(PYTEST) -q

testcov:
	$(PYTEST) -q --cov=src --cov-report=term-missing

test-integration:
	$(PYTEST) --override-ini addopts= -p no:cov -m integration tests/integration

revision:
	@if [ -z "$(m)" ]; then echo "Use: make revision m='message'"; exit 1; fi
	$(ALEMBIC) revision --autogenerate -m "$(m)"

upgrade:
	$(ALEMBIC) upgrade head

downgrade:
	$(ALEMBIC) downgrade -1

migrate: upgrade

up:
	API_PORT=$(API_PORT) $(COMPOSE) up --build -d

down:
	$(COMPOSE) down

logs:
	$(COMPOSE) logs -f --tail=200 api postgres

dev:
	$(COMPOSE) up -d postgres
	$(UV) app.main:app --host 0.0.0.0 --port 8000 --reload

smoke:
	curl -s http://localhost:8000/health | jq . ; \
	curl -s -X POST http://localhost:8000/api/v1/users -H "Content-Type: application/json" -d '{"email":"smoke@example.com","full_name":"Smoke Test"}' | jq . ; \
	curl -s http://localhost:8000/api/v1/users | jq . ; \
	curl -s http://localhost:8000/metrics | head -n 5

smoke-fly:
	@echo "Checking Fly health endpoint for $(FLY_APP)" ; \
	curl -fsS https://$(FLY_DOMAIN)/health | jq .

admin-credentials: deps
	$(PY) scripts/admin_credentials.py --write --fly-sync --fly-app $(FLY_APP)

worker: deps
	$(PY) scripts/run_worker.py
