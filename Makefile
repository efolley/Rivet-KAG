.PHONY: install dev-backend dev-frontend lint test up down

install:
	uv sync
	cd frontend && npm install

dev-backend:
	uv run uvicorn src.main:app --reload

dev-frontend:
	cd frontend && npm run dev

lint:
	uv run ruff check src tests
	uv run mypy
	cd frontend && npx tsc --noEmit

test:
	uv run pytest

up:
	docker compose up --build

down:
	docker compose down
