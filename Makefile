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

API_PORT_FILE := $(strip $(shell awk -F= '$$1=="API_PORT"{print $$2}' .env 2>/dev/null))
POSTGRES_PORT_FILE := $(strip $(shell awk -F= '$$1=="POSTGRES_PORT"{print $$2}' .env 2>/dev/null))
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

CORE_DIR ?= ../tv7-core
CORE_URL ?= https://github.com/TV7-Clip-Studio/tv7-core.git
SKIP_CORE ?= 0

ifeq ("$(SKIP_CORE)","1")
  # Core checks skipped (CI override or emergency)
else
  ifeq ("$(wildcard $(CORE_DIR))","")
  $(error tv7-core not found. Please clone it as a sibling directory: $(CORE_DIR) (or set SKIP_CORE=1 to bypass))
  endif
  -include Makefile.core
endif

.PHONY: deps run test testcov fmt lint type sec precommit \
        revision upgrade downgrade migrate up down build restart logs dev smoke \
        smoke-fly \
        test-integration \
        core-init

deps:
	@[ -d $(VENV) ] || python -m venv $(VENV)
	@$(PIP) -q install --upgrade pip
	@$(PIP) -q install -e ".[dev]"
	@$(VENV)/bin/pre-commit install

core-init:
	@if [ -d "$(CORE_DIR)/.git" ]; then echo "tv7-core already present at $(CORE_DIR)"; exit 0; fi
	@mkdir -p "$(dir $(CORE_DIR))"
	@git clone --depth 1 "$(CORE_URL)" "$(CORE_DIR)"

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
	COMPOSE_PROJECT_NAME=$(COMPOSE_PROJECT_NAME) API_PORT=$(API_PORT) POSTGRES_PORT=$(POSTGRES_PORT) $(COMPOSE) up $(UP_FLAGS)

down:
	COMPOSE_PROJECT_NAME=$(COMPOSE_PROJECT_NAME) $(COMPOSE) down

logs:
	COMPOSE_PROJECT_NAME=$(COMPOSE_PROJECT_NAME) $(COMPOSE) logs -f --tail=200 api postgres

dev:
	COMPOSE_PROJECT_NAME=$(COMPOSE_PROJECT_NAME) $(COMPOSE) up -d postgres
	$(UV) app.main:app --host 0.0.0.0 --port 8000 --reload

smoke:
	curl -s http://localhost:8000/health | jq . ; \
	curl -s http://localhost:8000/metrics | head -n 5 ; \
	PYTHONPATH=src $(PY) scripts/cleanup_media.py

smoke-fly:
	@echo "Checking Fly health endpoint for $(FLY_APP)" ; \
	curl -fsS https://$(FLY_DOMAIN)/health | jq .
