COMPOSE := docker compose
DEV     := docker compose -f docker-compose.yml -f docker-compose.dev.yml
# Disposable database for tests (tables are dropped and recreated). `make testdb` starts it.
TEST_DATABASE_URL ?= postgresql+asyncpg://postgres:postgres@localhost:55432/seyvix_test

.DEFAULT_GOAL := help
.PHONY: help env dev dev-down up down build ps logs migrate backup restore config \
        testdb test test-backend test-bot test-web lint lint-backend lint-bot lint-web

help: ## Show targets
	@grep -E '^[a-z-]+:.*##' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  %-14s %s\n", $$1, $$2}'

env: ## Create .env with generated secrets
	scripts/init-env.sh

dev: ## Dev stack: hot reload, Vite on :5173, API on :8000
	$(DEV) up --build

dev-down: ## Stop the dev stack
	$(DEV) down

up: ## Production-like stack (build locally, wait until healthy)
	$(COMPOSE) up -d --build --wait

down: ## Stop the stack (data volumes are kept)
	$(COMPOSE) down

build: ## Build all images
	$(COMPOSE) --profile telegram build

ps: ## Service status
	$(COMPOSE) ps

logs: ## Follow logs (make logs s=api)
	$(COMPOSE) logs -f --tail=200 $(s)

migrate: ## Apply database migrations
	$(COMPOSE) run --rm migrate

backup: ## Back up DB + files into ./backups
	scripts/backup.sh

restore: ## Restore a backup (make restore b=backups/<stamp>)
	scripts/restore.sh $(b)

config: ## Validate compose files
	$(COMPOSE) --profile telegram config --quiet
	$(DEV) --profile telegram config --quiet

testdb: ## Start the disposable test Postgres on :55432
	docker run -d --name seyvix-testdb -p 127.0.0.1:55432:5432 \
		-e POSTGRES_PASSWORD=postgres -e POSTGRES_DB=seyvix_test pgvector/pgvector:0.8.7-pg16-bookworm

test: test-backend test-bot test-web ## Run all tests

test-backend:
	cd backend && TEST_DATABASE_URL=$(TEST_DATABASE_URL) uv run pytest

test-bot:
	cd telegram-bot && uv run pytest

test-web:
	cd web && npm test

lint: lint-backend lint-bot lint-web ## Run linters and type checks

lint-backend:
	cd backend && uv run ruff check app tests && uv run mypy

lint-bot:
	cd telegram-bot && uv run ruff check telegram_bot tests

lint-web:
	cd web && npm run typecheck
