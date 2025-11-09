VENV := .venv
PY := $(VENV)/bin/python
PIP := $(VENV)/bin/pip
UV := $(VENV)/bin/uvicorn
PYTEST := $(VENV)/bin/pytest
PLAYWRIGHT := $(VENV)/bin/playwright
BLACK := $(VENV)/bin/black
RUFF := $(VENV)/bin/ruff
MYPY := $(VENV)/bin/mypy
BANDIT := $(VENV)/bin/bandit
ALEMBIC := $(VENV)/bin/alembic
COMPOSE ?= docker compose
PWHEADLESS ?= true
PWSLOWMO ?= 0
UI_TEST ?= tests/ui/test_admin_ingest_ui.py::test_admin_login_and_ingest_flow
NON_UI_TEST_ARGS ?= tests --ignore=tests/ui

API_PORT_FILE := $(strip $(shell awk -F= '$$1=="API_PORT"{print $$2}' .env 2>/dev/null))
POSTGRES_PORT_FILE := $(strip $(shell awk -F= '$$1=="POSTGRES_PORT"{print $$2}' .env 2>/dev/null))
REDIS_PORT_FILE := $(strip $(shell awk -F= '$$1=="REDIS_PORT"{print $$2}' .env 2>/dev/null))
COMPOSE_PROJECT_FILE := $(strip $(shell awk -F= '$$1=="COMPOSE_PROJECT_NAME"{print $$2}' .env 2>/dev/null))

ifeq ($(API_PORT_FILE),)
API_PORT ?= 8000
else
API_PORT ?= $(API_PORT_FILE)
endif

ifeq ($(POSTGRES_PORT_FILE),)
POSTGRES_PORT ?= 5432
else
POSTGRES_PORT ?= $(POSTGRES_PORT_FILE)
endif

ifeq ($(REDIS_PORT_FILE),)
REDIS_PORT ?= 6379
else
REDIS_PORT ?= $(REDIS_PORT_FILE)
endif

ifeq ($(COMPOSE_PROJECT_FILE),)
COMPOSE_PROJECT_NAME ?= $(notdir $(CURDIR))
else
COMPOSE_PROJECT_NAME ?= $(COMPOSE_PROJECT_FILE)
endif

FLY_APP ?= forgotten-app
FLY_DOMAIN ?= $(FLY_APP).fly.dev
DETACH ?= 0

UP_FLAGS := --build
ifeq ($(filter 1 true yes,$(DETACH)),)
else
UP_FLAGS += -d
endif

.PHONY: deps run test testcov fmt lint type sec precommit \
        revision upgrade downgrade migrate up down build restart logs dev smoke \
        smoke-fly pipeline-smoke ui-smoke \
        admin-credentials worker \
        test-integration test-ui test-ui-visual test-suite

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

test-ui:
	PWHEADLESS=$(PWHEADLESS) PWSLOWMO=$(PWSLOWMO) $(PYTEST) -v --no-cov $(UI_TEST)

test-ui-visual:
	PWHEADLESS=false PWSLOWMO=500 $(PYTEST) -v --no-cov $(UI_TEST)

test-suite:
	$(PYTEST) -v --no-cov $(NON_UI_TEST_ARGS)
	$(MAKE) test-ui

revision:
	@if [ -z "$(m)" ]; then echo "Use: make revision m='message'"; exit 1; fi
	$(ALEMBIC) revision --autogenerate -m "$(m)"

upgrade:
	$(ALEMBIC) upgrade head

downgrade:
	$(ALEMBIC) downgrade -1

migrate: upgrade

up:
	COMPOSE_PROJECT_NAME=$(COMPOSE_PROJECT_NAME) API_PORT=$(API_PORT) POSTGRES_PORT=$(POSTGRES_PORT) REDIS_PORT=$(REDIS_PORT) $(COMPOSE) up $(UP_FLAGS)

down:
	COMPOSE_PROJECT_NAME=$(COMPOSE_PROJECT_NAME) $(COMPOSE) down

logs:
	COMPOSE_PROJECT_NAME=$(COMPOSE_PROJECT_NAME) $(COMPOSE) logs -f --tail=200 api postgres

dev:
	COMPOSE_PROJECT_NAME=$(COMPOSE_PROJECT_NAME) $(COMPOSE) up -d postgres
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

pipeline-smoke: deps
	$(PYTEST) --override-ini addopts= -m regression -q

ui-smoke: deps
	$(PLAYWRIGHT) install --with-deps chromium >/dev/null
	UI_BASE_URL=$${UI_BASE_URL:-http://127.0.0.1:$(API_PORT)} PWHEADLESS=$(PWHEADLESS) PWSLOWMO=$(PWSLOWMO) $(PYTEST) --no-cov --override-ini addopts= -m ui tests/ui
