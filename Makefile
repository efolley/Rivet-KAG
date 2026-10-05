.PHONY: neo4j postgres redis kafka platform wait-platform up ingest eval judge deepeval gates alerts dev dev-backend dev-frontend install lint test docker-up docker-down docker-ingest docker-logs

neo4j:
	brew services start neo4j

postgres:
	brew services start postgresql@16

redis:
	brew services start redis

kafka:
	brew services start kafka

platform: neo4j postgres redis kafka

# brew services start returns as soon as launchd accepts the job, not once the service is
# actually accepting connections -- `make dev` right after `make platform` can race a cold
# Postgres/Neo4j/Kafka boot. Poll each port instead of a fixed sleep, since boot time varies by
# machine and whether brew is starting these fresh or they were already running.
wait-platform:
	@echo "Waiting for neo4j (7687), postgres (5432), redis (6379), kafka (9092)..."
	@for port in 7687 5432 6379 9092; do \
		until nc -z localhost $$port 2>/dev/null; do sleep 1; done; \
	done
	@echo "Platform is up."

# One command for local dev: start the four brew services (if not already running), wait for
# them to actually accept connections, then run the API + UI. Deliberately not Docker -- this
# project dropped Docker earlier (see CLAUDE.md) because Milvus Lite's embedded, single-process
# file lock and brew-managed Neo4j/Postgres/Redis/Kafka don't gain anything from containerizing;
# this just gives the same "one command" convenience without reversing that decision.
up: platform wait-platform dev

ingest:
	uv run python -m utils.upload all

eval:
	uv run python -m evals.check_retrieval

judge:
	uv run python -m evals.judge

# deepeval/gates need the opt-in `eval` dependency group (not installed by default -- see
# pyproject.toml's addopts and evals/deepeval_suite.py's module docstring for why).
deepeval:
	uv run --group eval python -m evals.deepeval_suite

gates:
	uv run --group eval python -m evals.release_gates

alerts:
	uv run python -m evals.check_alerts

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

# Containerized alternative to `make up` -- see docker-compose.yml and the README's "Docker"
# section. `docker-up` builds and starts everything (API, UI, Neo4j, Postgres, Redis, Kafka);
# run `make docker-ingest` once afterward to load source_data/ before asking real questions.
docker-up:
	docker compose up --build

docker-down:
	docker compose down

docker-ingest:
	docker compose exec api uv run python -m utils.upload all

docker-logs:
	docker compose logs -f
