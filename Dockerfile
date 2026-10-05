# Optional container packaging for the FastAPI backend -- local dev still defaults to uv +
# brew services (see CLAUDE.md's "Stack and why"); this exists for anyone who wants the whole
# stack (API, UI, Neo4j, Postgres, Redis, Kafka) up with one `docker compose up`, e.g. a quick
# demo on a machine without Homebrew. See docker-compose.yml and the README's "Docker" section.
FROM python:3.12-slim AS base

# libgomp1: faiss (pulled in by pymilvus/fastembed) needs it at runtime; build-essential: a few
# transitive deps (e.g. tokenizers) compile from source on slim's glibc if no prebuilt wheel
# matches, so it's kept rather than trimmed.
RUN apt-get update && apt-get install -y --no-install-recommends \
      build-essential libgomp1 curl \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.5 /uv /uvx /usr/local/bin/

WORKDIR /app

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/app/.venv \
    PATH="/app/.venv/bin:$PATH"

# Dependencies first so the layer is reusable across source-only changes.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project --no-dev

COPY src ./src
COPY utils ./utils
COPY evals ./evals

RUN uv sync --frozen --no-dev

EXPOSE 8000

CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]
