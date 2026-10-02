# CLAUDE.md

Guidance for whoever (human or agent) develops in this repo next. `README.md` is for people using
or evaluating Rivet KAG; this file is for people changing it.

## Development philosophy — read before adding anything

**The goal is to test a production-shaped AI system design simply — not to build a product or a
polished demo.** Concretely:

- Keep each piece the smallest version that genuinely demonstrates the pattern (typed stage
  interfaces, graceful degradation, real tests, real-ish cost/observability design). Don't add
  scope, configurability, or UI polish beyond what's asked, even if it would be "more complete."
- **Every real component gets a handful of mocked unit tests** (3-5 is the usual size) in
  `tests/`, run by `make test` / CI — fast, fully offline, no network, no live DB, no API key.
  That's the primary test, not an afterthought.
- **"Does it actually work" is a separate, smaller check, not a feature to build out.** Scripts
  under `evals/` (`check_retrieval.py`, `judge.py`) hit the *live* databases/API to prove the real
  thing works end to end, not just that the mapping code is correct. They're deliberately small,
  hand-rolled, and not part of CI — run manually, on demand.
- **Verify before claiming something works.** At minimum, an offline construction smoke test; a
  live call against the real API/DB when credentials are available. Without a valid API key,
  confirm the request still reaches the real endpoint and fails for the *expected* reason (a real
  401, not a malformed-request error) — that proves the wiring, even though the happy path is
  unverified. Say plainly when only the failure path has been checked; don't imply more.
- Never commit or push without being explicitly asked, no matter how large the change.

## Stack and why

- **uv-only, no Docker.** All Python dependency management, venvs and running go through `uv`
  (`uv sync`, `uv run ...`). Docker was deliberately removed earlier in this project's history —
  don't reintroduce it unless asked.
- **Milvus runs embedded** (Milvus Lite: a local file at `data/milvus.db`), not a server — nothing
  to install for it. It locks its file to one process; `src/clients/milvus.py`'s `milvus_session()`
  context manager opens and *fully releases* it (closes the client, then calls
  `milvus_lite.server_manager.server_manager_instance.release_server(path)`) per operation, so the
  API and the CLI can take turns. Use that context manager for any new Milvus call site — don't
  hold a client open across requests.
- **Neo4j, Postgres, Redis and Kafka are all real external dependencies** — installed via
  `brew install neo4j postgresql@16 redis kafka` and run as background services (`make platform`
  starts all four). Kafka 4.x runs standalone in KRaft mode (no Zookeeper), so like the others
  it's a single `brew services start` away — not the heavy multi-process setup older Kafka needed.
  This is an accepted, deliberate exception to "uv-only": things that can't be embedded run as
  local services instead of being skipped or dockerized.
- **`frontend/`** is a separate, thin concern (Vite + React + TS, `npm`) talking to FastAPI over
  `/api/*`. It's a UI to exercise the backend, not a product — keep additions there equally small.

## The stub/real dual-path pattern

Every LLM- or database-backed pipeline stage has a stub and a real implementation, chosen in
`src/pipeline/factory.py`:

| Stage | Stub (default) | Real | Gated by |
|---|---|---|---|
| Retrieval (vector, graph) | `StubVectorRetriever`, `StubGraphRetriever` — canned citations | `MilvusRetriever`, `Neo4jRetriever` | `USE_STUBS=false` |
| Parse / route | `StubParser` — always queries both sources | `LangChainRouter` | `ANTHROPIC_API_KEY` set |
| Answer | `StubAnswerer` — canned text | `DeepAgentAnswerer` | `ANTHROPIC_API_KEY` set |
| PII masking | *(none — always real)* | `RegexPIIMasker` | always |

Two independent gates, not one: retrieval needs *databases*, the LLM stages need *credentials* —
different failure modes. CI sets neither, so it always runs the fully-stubbed path; this is why
`tests/` must never require a live DB or a real API key, and why `.env.example` ships with
`USE_STUBS=true` and an empty `ANTHROPIC_API_KEY`.

Every real LLM stage **catches its own failures and falls back to the stub-equivalent behavior
for that one request** — the router falls back to querying both sources, the answerer falls back
to showing the raw retrieved citations — rather than raising. A bad LLM response should degrade
the answer, never 500 the request. When you add a new LLM-backed stage, test the fallback
explicitly (mock the failure, assert what comes back), not just the happy path.

## The platform services are best-effort, not gated

Unlike the LLM pipeline stages, Postgres (chat history, audit log, ingestion jobs), Redis
(response cache) and Kafka (event publishing) have no stub/real split and no settings flag —
there's no meaningful "fake Postgres" to swap in. Instead, every place that touches one of them
on the request path (`src/api/routes/chat.py`, `src/api/routes/files.py`) wraps the call in its
own `try/except`, logs a warning, and carries on. A `/api/chat` or `/api/files` call must return
its normal response even with all three completely unreachable — verified by pointing
`DATABASE_URL`/`REDIS_URL`/`KAFKA_BOOTSTRAP_SERVERS` at unreachable hosts and confirming the
full test suite (and a live curl) still gets 200s. Follow this pattern for any new platform-service
call: wrap it, log it, never let it be the reason a user-facing request fails.

`src/db/engine.py`'s `get_session()` is lazy by design (entering the `AsyncSession` context
manager doesn't open a connection — SQLAlchemy only connects on first query), which is *why*
wrapping just the `db.add()/commit()` call in try/except is enough; the dependency itself never
raises just because Postgres is down.

## Commands

```bash
make install     # uv sync + npm install
make platform    # start neo4j, postgres, redis and kafka (brew services), once
make ingest      # load source_data/ into Milvus + Neo4j
make dev         # API on :8000 + UI on :5173
make lint        # ruff + mypy (src, utils, evals, tests) + tsc --noEmit
make test        # pytest — fast, offline, CI-safe, never touches a live service
make eval        # live retrieval-accuracy check against the real databases
make judge       # live LLM-as-a-judge run — needs ANTHROPIC_API_KEY, costs real money
```

## Conventions

- Always `uv run <tool>` — never a bare `python`/`pip`/`pytest`.
- Ruff and mypy both run strict. `pyproject.toml`'s `[tool.mypy] files` lists the packages that
  are type-checked (`src`, `utils`, `evals`) — add a new top-level package there; `tests/` is
  deliberately left out of mypy's scope.
- No comments unless the *why* isn't obvious from the code itself (a non-obvious constraint, a
  workaround, a subtle invariant) — not a restatement of what the code does.
- **Adding a new pipeline stage**: define its `Protocol` in `src/pipeline/base.py` if one doesn't
  exist, write stub and real implementations, wire the choice into `factory.py`, and if it's a new
  *stage* (not just a new implementation of an existing one) add it to `orchestrator.py`'s stage
  list and `StageTrace`.
- **Adding a new external dependency**: confirm it actually installs and inspect its real,
  installed API (`uv run python -c "import X; help(X.thing)"` / `inspect.signature(...)`) before
  writing code against a remembered API shape. Fast-moving libraries (LangChain, DeepAgents,
  LlamaIndex, pymilvus) drift from training data quickly — several real bugs in this project
  (see below) were caught exactly this way, not by reading docs.

## Known gotchas

- **Milvus Lite lock**: closing a `MilvusClient` isn't enough to release its file lock — see the
  `milvus_session()` note above. Forgetting this makes the *next* process to open the same file
  hang or fail.
- **`pymilvus.query()` returns a lazily-hydrated list.** Sorting it in place only sees whichever
  field was last accessed before the sort. Copy to plain dicts first:
  `sorted((dict(r) for r in rows), key=...)`.
- **`ChatAnthropic` (langchain-anthropic) + mypy strict**: it's a pydantic v2 model using PEP 681
  (`dataclass_transform`) synthesis, so mypy's synthesized constructor wants kwargs by their
  pydantic **alias**, not the Python field name — `model_name=`, not `model=`; `max_tokens_to_sample=`,
  not `max_tokens=`; `api_key=SecretStr(...)`, not a plain `str`. Works at runtime either way; only
  mypy enforces the alias form.
- **`MarkdownReader.parse_tups()` (LlamaIndex)** only starts a new chunk when a heading *level*
  repeats, not on every heading — it silently merges a document's first section into its title.
  Don't use it for "one chunk per heading"; split markdown directly instead (see
  `src/ingestion/loaders.py`).
- **A module-level `@lru_cache`d async client (Kafka, Redis, Milvus, ...) can hang forever across
  tests.** `src/clients/kafka.py`'s `AIOKafkaProducer` is started once and cached for the process.
  In production that's correct (uvicorn keeps one event loop for its whole life). In tests,
  `pytest-asyncio` gives each test function its *own* event loop by default — a producer started
  inside one test's loop hangs forever if a later test's (different) loop awaits on it. Fix: never
  let tests exercise the real client at all (see `tests/conftest.py`'s autouse `_no_real_kafka`
  fixture) rather than trying to make the client loop-safe. If you add another cached async
  client, give it the same treatment up front — this one cost real debugging time to track down,
  since every *individual* test file passed; only the full suite (shared process, multiple loops)
  hung.
- **Testing Postgres-backed routes**: `tests/conftest.py`'s `db_session` fixture overrides
  `get_session` with a real, in-memory SQLite database (`sqlite+aiosqlite:///:memory:`, with
  `poolclass=StaticPool` — without it, each connection gets its *own* empty in-memory DB and
  tables created in one are invisible to another). Use this fixture for anything that needs real
  CRUD behavior (see `tests/test_auth.py`). For testing the "Postgres is down" degrade path
  specifically, `broken_db_session` points `get_session` at a real but unreachable Postgres URL
  instead — this matters because the lazy-connection behavior (see above) only reproduces
  faithfully with a real engine, not a mock that raises eagerly.
