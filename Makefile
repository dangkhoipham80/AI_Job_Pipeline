# JobPilot dev tasks. See PLAN.md / CLAUDE.md.
.PHONY: help venv install install-all db-up db-down migrate api web crawl slack test config lint

help:
	@echo "JobPilot targets:"
	@echo "  make install     - create .venv and install base + dev deps (Phase 0)"
	@echo "  make install-all - install every phase extra (data,api,crawler,tailor,slack)"
	@echo "  make config      - validate & print resolved config (Phase 0)"
	@echo "  make db-up     - start Postgres via docker-compose"
	@echo "  make db-down   - stop Postgres"
	@echo "  make migrate   - alembic upgrade head (Phase 2+)"
	@echo "  make api       - run FastAPI backend (Phase 2+)"
	@echo "  make web       - run React dashboard (Phase 4+)"
	@echo "  make crawl     - crawl jobs into DB (Phase 3+)"
	@echo "  make slack     - run Slack bot, secondary channel (Phase 7+)"
	@echo "  make test      - run pytest"
	@echo "  make dev       - db-up + api + web together (Phase 4+)"

install:
	python -m venv .venv
	.venv/Scripts/python -m pip install -U pip
	.venv/Scripts/python -m pip install -e ".[dev]"

install-all:
	.venv/Scripts/python -m pip install -e ".[all,dev]"

config:
	python -m jobpilot.cli config

db-up:
	docker-compose up -d postgres

db-down:
	docker-compose down

migrate:
	alembic upgrade head

api:
	uvicorn jobpilot.api.main:app --reload --port 8000

web:
	cd web && npm run dev

crawl:
	python -m jobpilot.cli crawl

slack:
	python -m jobpilot.slack.app

test:
	pytest jobpilot/tests

lint:
	ruff check jobpilot && black --check jobpilot

dev: db-up api
