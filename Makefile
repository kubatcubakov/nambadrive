.PHONY: help backend-test backend-lint frontend-check compose-validate up down migrate

help:
	@echo "backend-test     Run backend pytest"
	@echo "backend-lint     Run ruff + mypy"
	@echo "frontend-check   Run npm typecheck/lint/build"
	@echo "compose-validate Validate AIO compose"
	@echo "up               Build/start AIO using deploy/aio/.env"
	@echo "down             Stop AIO"
	@echo "migrate          Run Alembic upgrade head in AIO"

backend-test:
	cd backend && pytest -q

backend-lint:
	ruff check backend/app backend/tests backend/alembic
	mypy backend/app

frontend-check:
	cd frontend && npm run typecheck && npm run lint && npm run build

compose-validate:
	docker compose -f deploy/aio/compose.yml --env-file deploy/aio/.env config >/dev/null

up:
	cd deploy/aio && docker compose --env-file .env up -d --build

down:
	cd deploy/aio && docker compose --env-file .env down

migrate:
	cd deploy/aio && docker compose --env-file .env run --rm backend alembic upgrade head
