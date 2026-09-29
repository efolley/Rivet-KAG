.PHONY: neo4j ingest eval judge dev dev-backend dev-frontend install lint test

neo4j:
	brew services start neo4j

ingest:
	uv run python -m utils.upload all

eval:
	uv run python -m evals.check_retrieval

judge:
	uv run python -m evals.judge

dev:
	$(MAKE) -j2 dev-backend dev-frontend

install:
	uv sync
	cd frontend && npm install

dev-backend:
	uv run uvicorn src.main:app --reload

dev-frontend:
	cd frontend && npm run dev

lint:
	uv run ruff check src utils evals tests
	uv run mypy
	cd frontend && npx tsc --noEmit

test:
	uv run pytest
