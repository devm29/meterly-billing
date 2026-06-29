SHELL := /bin/bash
BACKEND := backend
WEB := web
VENV := $(BACKEND)/.venv
PY := $(VENV)/bin/python
# Prefer a known-good Homebrew PG 17/16 over whatever pg_config happens to point at.
PG_BIN ?= $(firstword $(wildcard /opt/homebrew/opt/postgresql@17/bin /opt/homebrew/opt/postgresql@16/bin /usr/local/opt/postgresql@17/bin /usr/local/opt/postgresql@16/bin) $(shell pg_config --bindir 2>/dev/null))
PG_DATA := .data/pg

.PHONY: help install db-up db-down migrate seed api worker web test lint typecheck format build loadgen ci

help:
	@grep -E '^[a-z-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-12s %s\n", $$1, $$2}'

install: ## Create the venv and install backend + web dependencies
	python3 -m venv $(VENV)
	$(VENV)/bin/pip install -q --upgrade pip
	$(VENV)/bin/pip install -q -e "$(BACKEND)[dev]"
	cd $(WEB) && pnpm install

db-up: ## Start local Postgres (5507) and Redis (6407) with data under .data/ (override PG_BIN=...)
	@$(PG_BIN)/postgres --version >/dev/null 2>&1 || (echo "No working postgres in PG_BIN=$(PG_BIN); run make db-up PG_BIN=/path/to/postgres/bin" && exit 1)
	@mkdir -p .data/redis
	@test -d $(PG_DATA) || ($(PG_BIN)/initdb -D $(PG_DATA) -U meterly --auth=trust -E UTF8 >/dev/null)
	@$(PG_BIN)/pg_ctl -D $(PG_DATA) -o "-p 5507 -k /tmp -c listen_addresses=localhost" -l .data/pg.log status >/dev/null || \
		$(PG_BIN)/pg_ctl -D $(PG_DATA) -o "-p 5507 -k /tmp -c listen_addresses=localhost" -l .data/pg.log start
	@$(PG_BIN)/createdb -h localhost -p 5507 -U meterly meterly 2>/dev/null || true
	@$(PG_BIN)/createdb -h localhost -p 5507 -U meterly meterly_test 2>/dev/null || true
	@redis-cli -p 6407 ping >/dev/null 2>&1 || redis-server --port 6407 --dir .data/redis --daemonize yes --save "" --appendonly no

db-down: ## Stop local Postgres and Redis
	-$(PG_BIN)/pg_ctl -D $(PG_DATA) stop
	-redis-cli -p 6407 shutdown nosave

migrate: ## Apply database migrations
	cd $(BACKEND) && .venv/bin/alembic upgrade head

seed: migrate ## Load six months of realistic demo data
	cd $(BACKEND) && .venv/bin/python scripts/seed.py

api: ## Run the API on :8107
	cd $(BACKEND) && .venv/bin/uvicorn meterly.api.app:create_app --factory --port 8107 --reload --reload-dir src

worker: ## Run the arq worker (period close, finalization, partitions)
	cd $(BACKEND) && .venv/bin/arq meterly.worker.main.WorkerSettings

web: ## Run the console on :3107
	cd $(WEB) && pnpm dev

loadgen: ## Hammer the ingestion endpoint
	cd $(BACKEND) && .venv/bin/python scripts/loadgen.py --events 50000 --batch 500 --concurrency 8

test: ## Backend and web test suites
	cd $(BACKEND) && .venv/bin/pytest -q
	cd $(WEB) && pnpm test

lint: ## Ruff + ESLint + Prettier check
	cd $(BACKEND) && .venv/bin/ruff check . && .venv/bin/ruff format --check .
	cd $(WEB) && pnpm lint && pnpm format:check

typecheck: ## mypy --strict + tsc --noEmit
	cd $(BACKEND) && .venv/bin/mypy
	cd $(WEB) && pnpm typecheck

format: ## Auto-format everything
	cd $(BACKEND) && .venv/bin/ruff format . && .venv/bin/ruff check --fix .
	cd $(WEB) && pnpm format

build: ## Production build of the console
	cd $(WEB) && pnpm build

ci: lint typecheck test build ## Everything CI runs
