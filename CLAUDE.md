# CLAUDE.md

Guidance for whoever (human or agent) develops in this repo next. `README.md` is for people using
or evaluating Rivet KAG; this file is for people changing it.

## Current progress (as of 2026-10-05)

**Branches:** `feat/phase_3` and `dev` have both been merged into `main` via PR. `main` is now
the up-to-date branch; the section below (dated 2026-10-04) predates that merge and is kept for
its narrative/verification detail, not as a description of current branch state.

**Since the merge (2026-10-05):** a README onboarding pass (a 5-minute zero-services quickstart,
a demo GIF at `docs/demo.gif`, API-only vs. UI-visible feature labeling, and a "Scope vs. a full
agent platform" section contrasting this project's single-agent design against a fuller
multi-agent/MCP/VLM architecture) and **Docker packaging** (`Dockerfile`, `frontend/Dockerfile`,
`docker-compose.yml` — see README's "Docker" section and the "Stack and why" update below). Both
landed directly on `main`.

**Done, in order** (each phase's README roadmap checkboxes are the source of truth — grep
`^## Roadmap` there for the exact state):
- Phase 0 (skeleton), Phase 1 (sample data, Milvus Lite + Neo4j, LlamaIndex ingestion, real
  retrieval + Cypher generation, LangChain router) — all on `main`.
- Phase 2 (DeepAgents answerer with Pydantic output, real PII masking, LLM-as-a-judge
  `evals/judge.py`, context merge/reranking/ROI compression) — **complete**, on `main` once
  `feat/phase_3` lands (currently also present on `feat/phase_3`, since the merge-context work was
  done on top of it). `src/pipeline/merge.py` now dedupes by id, ranks by retriever score
  (unscored last), and greedily trims to a token budget (default 2,000, cheap char-based estimate)
  — no summarization step, verbatim-or-dropped.
- Phase 3 (Platform: JWT auth, Postgres, Redis cache, Kafka events) — now on `main` (see the
  branch note above). See the README's "Platform: auth, history and messaging" section for what's
  real. Docker packaging was postponed as of this writing (2026-10-04) but has since been added —
  see the "Since the merge" note above and the "Stack and why" update below; don't trust this
  specific line over those.

**Not started:** demo GIF and the "Agent actions" backlog item — everything else in Phase 4 is
now done (see below). The "Production readiness" section of the README is a *design*, not code,
for what's still missing — don't assume anything there is implemented without checking.

**Done on `dev` (2026-10-04):**
- **Prompt caching for the answerer's system prompt (Anthropic only)** —
  `src/pipeline/answering/agent.py`'s `_build_system_prompt` sends a `SystemMessage` with a
  `cache_control: {"type": "ephemeral"}` breakpoint for `LLM_PROVIDER=anthropic`; OpenAI/Ollama
  get the plain string (OpenAI caches automatically with no opt-in API, Ollama has no caching
  concept). **Real bug caught and fixed while building this**: the obvious-looking approach —
  putting `cache_control` inside `TextContentBlock`'s typed `extras` field — silently drops it;
  `langchain_anthropic`'s `_format_text_block` only reads a bare top-level `cache_control` key
  for this block type, not `extras` (confirmed by inspecting `_format_messages`'s actual output,
  not just trusting the types). Regression-tested in
  `tests/test_agent.py::test_build_system_prompt_cache_control_reaches_the_wire_format` against
  the real formatted output, not just our own message construction. Verified live against the
  real endpoint with the known out-of-credit key: identical `400` billing error as before, not a
  different "malformed request" error, confirming the request shape is accepted — same standard
  as every other unverified-happy-path item here. **Tool-schema caching is not implemented**:
  DeepAgents builds its own built-in tool list internally with no hook to attach `cache_control`
  to it; would need forking/monkeypatching DeepAgents, judged out of scope. Whether the cache
  actually *hits* on repeat requests (non-zero `cache_read_tokens`) is unverified for the same
  reason as the rest of the Anthropic happy path — no credit on the available key.
- **Per-stage cost accounting + pre-flight budget rejection** — `src/pipeline/pricing.py` (a
  small `PRICING` table covering only the models this project's router/answerer can actually
  select, `PARSE_BUDGET_USD`/`ANSWER_BUDGET_USD`/`TOTAL_BUDGET_USD` constants matching the
  README's cost table, `usage_from_ai_message`/`cost_usd` helpers). `Plan` and the new
  `AnswerResult` dataclass (both in `src/pipeline/base.py`, replacing `Answerer.answer()`'s bare
  `str` return) now carry `model`/`usage`/`cost_usd`; `StubParser`/`StubAnswerer` leave them
  `None` (no LLM call, not $0.00 — "unknown" vs "free" is a real distinction the pricing table
  enforces: an unpriced model also returns `None`, never a guessed price).
  `LangChainRouter.parse()` switched to `with_structured_output(..., include_raw=True)` to get
  at the raw `AIMessage.usage_metadata` for cost accounting (its plain-`RouterDecision` return
  was discarding that). `DeepAgentAnswerer._estimate_cost_usd` runs a real pre-flight check via
  each model's own `get_num_tokens_from_messages` — Anthropic's is backed by the live
  `messages.count_tokens` API (confirmed live: reaches `api.anthropic.com`, a real 401/400 comes
  back when the call itself can't be billed, exactly the existing "reaches the real endpoint and
  fails for the expected reason" verification standard), OpenAI's is a local `tiktoken` count,
  Ollama's a cheap local heuristic — one call site, no provider branching needed. Exceeding
  `ANSWER_BUDGET_USD` at the worst-case estimate (input tokens + the configured 1024-token output
  cap) skips the real LLM call entirely (`AnswerResult.budget_rejected=True`, `cost_usd=0.0`).
  `Pipeline.run()` sums `plan.cost_usd + answer_result.cost_usd` into `ChatResponse.total_cost_usd`
  (`None` if either is unknown, never silently treated as $0) and logs a warning if it exceeds
  `TOTAL_BUDGET_USD`; both values are also pushed into the per-stage Langfuse spans. Tests:
  `tests/test_pricing.py` (new) and new cases in `tests/test_agent.py`/`tests/test_router.py` —
  all fully mocked (`ChatAnthropic.get_num_tokens_from_messages` is monkeypatched at the class
  level, since it's a pydantic model and otherwise makes a real network call even under a fake
  key, which the first version of these tests actually did before being fixed). Verified live
  through a running Ollama-backed answerer: real `input_tokens`/`output_tokens`/`cost_usd=0.0`
  (Ollama is free) land in the trace; the router's Anthropic call failed on the same out-of-credit
  key as before and fell back cleanly, leaving `total_cost_usd=null` (not a wrong $0) exactly per
  the "unknown stage cost poisons the total" design. Prompt caching and job-level spend limits
  both followed in later sessions on this same date (see below).
- **Local-only Langfuse tracing** — `src/clients/langfuse.py` + `Pipeline.run()` in
  `src/pipeline/orchestrator.py`. Hard-guarded to loopback hosts only (`_is_local()`); never
  talks to Langfuse Cloud regardless of `LANGFUSE_HOST`. No bundled local Langfuse server —
  self-hosting it needs Postgres+ClickHouse+Redis+object storage, out of scope here; without one
  running, every span attempt fails to connect and is swallowed exactly like a Postgres/Redis/
  Kafka outage (best-effort, never breaks the request — see `tests/test_tracing.py`). Implements
  the per-request/per-stage fields buildable from what the pipeline returns today; token/cost/
  model fields wait on the cost-accounting item below (see README's "Observability and audit
  trail" for the exact field-by-field state).
- **Per-request model picker** — `GET /api/models` serves a small catalog (1-2 cheap models per
  provider); `ChatRequest.llm_provider`/`llm_model` override the server default per request,
  resolved through a pipeline cached per (provider, model) pair (`src/api/deps.py`).
- **Fixed `DeepAgentAnswerer` silently dropping a model's real answer** whenever DeepAgents'
  `structured_response` extraction failed (common with smaller models not reliably tool-calling
  for structured output) — it now recovers the agent's final plain-text message first. Confirmed
  `llama3.2:latest` answers one question wrong regardless of this fix (a model-quality issue, not
  a code bug); `.env`'s local default moved to `qwen2.5:14b`, which answers it correctly.
- **DeepEval suite, release gates, and alerting** (the rest of Phase 4):
  - `evals/golden_questions.json` grew from 10 to 30 (20 new questions, all live-verified
    30/30 — see below). Every question is grounded in `source_data/`; one new vector question
    ("When is VPN access enabled for a new employee?") turned out to top-match a *different*
    doc than first picked (semantically reasonable ambiguity between `onboarding_guide.md` and
    `vpn_and_access_policy.md`) and its expected source was corrected to match reality rather
    than forcing the question to be less natural.
  - `evals/deepeval_suite.py` (`make deepeval`, needs `uv sync --group eval`): `GEval`
    (correctness rubric) + `FaithfulnessMetric` (citation faithfulness) via a custom
    `AnthropicJudgeModel` (`deepeval.models.DeepEvalBaseLLM` wrapping `ChatAnthropic`) so the
    judge is Claude, not DeepEval's OpenAI-shaped default. **Real bug found and fixed**:
    `deepeval` registers a pytest plugin (`deepeval.plugins.plugin`) that calls `load_dotenv()`
    during pytest's *plugin-loading* phase — before `conftest.py` ever runs, so its existing
    dotenv-neutering was too late. Caught because installing the `eval` group and running the
    full suite made one unrelated test fail (`.env`'s real `LLM_PROVIDER=ollama` leaked into
    `os.environ`, same failure *shape* as the original pymilvus `load_dotenv()` bug, different
    source). `deepeval` is now a non-default uv dependency group (`eval`), and
    `pyproject.toml` carries `addopts = "-p no:deepeval"` as defense in depth even if someone
    runs tests with the group installed — verified both ways (plugin absent, plugin present
    with the flag) actually prevent the leak.
  - `evals/gates.py` / `evals/alerts.py`: the release-gate and alert-condition *decision logic*
    as pure, `None`-aware functions (unit-tested offline — `tests/test_gates.py`,
    `tests/test_alerts.py`, 26 tests total), separate from `evals/release_gates.py` /
    `evals/check_alerts.py`, which gather the live inputs. A missing metric is never silently
    "pass" for a blocking gate (it blocks) or silently "OK" for an alert (it reports "not
    computable") — the one exception is HITL, which is designed to always report
    "not applicable" since no production traffic exists in this project to sample from.
  - `chat_audit_log` gained a `cost_usd` column (`ChatResponse.total_cost_usd`, round-tripped
    through Redis caching for free since it's already a `ChatResponse` field) specifically to
    feed `check_alerts.py`'s cost condition. `Base.metadata.create_all` doesn't alter existing
    tables, so the live dev Postgres here needed a manual `ALTER TABLE ... ADD COLUMN cost_usd
    double precision;` — documented in README since any other pre-existing deployment would
    need the same.
  - **Real bug found and fixed while verifying `check_alerts.py` live**: the first version
    compared a Python-computed `datetime.now(UTC)` against `chat_audit_log.created_at`
    (`TIMESTAMP WITHOUT TIME ZONE`, from Postgres's own `now()`) and silently returned zero
    rows — the two clocks disagreed by ~4 hours in this environment. Fixed by computing every
    window boundary with Postgres's own `now() - interval` instead of a client-side timestamp,
    so the comparison can never disagree with what wrote the value.
  - **Verified live, not just offline**: `make eval` genuinely 30/30 against real Milvus+Neo4j;
    `make deepeval` and `make gates` both reach `api.anthropic.com` for real and fail with the
    same known out-of-credit `400` (not a different, malformed-request error) for both the
    GEval and FaithfulnessMetric calls; `make alerts` run against real traffic from `make dev`
    correctly computed non-trivial P95 latency / error rate / empty-result rate from live rows,
    and correctly reported cost as "not computable" for that traffic specifically (every request
    in this environment has a `None` `total_cost_usd` because of the router's own known
    out-of-credit failure — not a bug in the alert plumbing).
  - CI's existing ruff step was silently skipping `utils` and `evals` entirely (only checked
    `src tests`) — fixed to match the Makefile's `lint` target now that `evals/` has real logic
    worth linting. Added `.github/workflows/release-gates.yml` as a `workflow_dispatch`-only
    job (not `push`/`pull_request` like `ci.yml`): this repo has no `ANTHROPIC_API_KEY` secret
    configured, so wiring it into every push would just fail for a reason unrelated to the code.
- **Job-level spend circuit breakers** — the "not yet implemented" item from the cost-accounting
  work above. Two independent breakers, both in `src/pipeline/pricing.py`:
  - **Per-session** (`SESSION_DAILY_BUDGET_USD = $1.00`): `Answerer.answer()`'s Protocol gained
    an optional `max_cost_usd` param (`src/pipeline/base.py`) that overrides
    `ANSWER_BUDGET_USD` for one call; `DeepAgentAnswerer` short-circuits to the existing
    fallback path immediately when `max_cost_usd <= 0`, *without* running the pre-flight
    token-count estimate first (a failed/unknown estimate must not accidentally let a
    zero-budget request through). `Pipeline.run()` threads a new `max_answer_cost_usd` param
    through. `src/api/routes/chat.py`'s `_session_spend_24h` sums `chat_audit_log.cost_usd` for
    the request's session over a rolling 24h window and passes `0.0` once over cap — best-effort
    like every other platform read (DB down -> don't block, not "assume over budget").
  - **Per-batch-job** (`BATCH_JOB_BUDGET_USD = $5.00`): `BatchBudget`, a tiny in-process
    accumulator with `.add(cost)`/`.check()` (raises `BudgetExceededError` once over), wired
    into `evals/judge.py`, `evals/deepeval_suite.py`, and `evals/release_gates.py`'s own
    latency/cost measurement pass — `release_gates.py` shares one tracker across all three so
    the whole run (not each phase) is capped at $5. `judge.py` also switched to
    `include_raw=True` (same pattern as the router) to get the judge call's own cost, not just
    the pipeline's.
  - **Two real bugs caught and fixed live, not in tests**: (1) comparing the database's own
    `now()` (fetched via `SELECT now()`) against `created_at` still failed with "can't subtract
    offset-naive and offset-aware datetimes" — turns out Postgres's `now()` returns a tz-aware
    `timestamptz` through asyncpg *regardless of the target column's own (naive) type*, so even
    the "ask the database what time it is" fix needed an explicit `.replace(tzinfo=None)`. (2)
    The first live test of the session breaker appeared to silently not fire — turned out the
    test question had already been answered once this session and was served straight from the
    Redis response cache, which doesn't key on `session_id` at all (by design, see
    `_cache_key`), so it never reaches the budget check in the first place; re-tested with a
    fresh question and confirmed `budget_rejected: true` plus the logged warning. Seeded a real
    over-cap row directly in Postgres to produce this live, not just via a mock.
  - All three new tests files' worth of coverage (`tests/test_pricing.py`'s `BatchBudget` cases,
    `tests/test_agent.py`'s `max_cost_usd=0.0` case, `tests/test_platform.py`'s three
    session-breaker route tests) are fully offline/mocked; `make judge` and `make gates` were
    re-run live afterward and still reach `api.anthropic.com` and fail with the same known
    out-of-credit `400` as always, confirming the budget bookkeeping didn't change the request
    shape.

**Live-tested on 2026-10-02** (platform services up via `make platform`, `.env` with
`USE_STUBS=false`): `make ingest` and `make eval` both ran clean — **10/10 live retrieval
accuracy** against real Milvus + Neo4j. A model router was added (`LLM_PROVIDER=anthropic|openai|
ollama`, answerer-only — see README's "Model router") so the answerer could run against a local
Ollama (`llama3.2:latest`) for free. With a real but **out-of-credit** Anthropic key (`ANTHROPIC_API_KEY`
valid, account balance too low): the LLM router hit a real `400` from `api.anthropic.com`
("credit balance too low") and **gracefully fell back to querying both sources**, confirmed live
(not mocked) for the first time; the Ollama-backed `DeepAgentAnswerer` then answered normally.
`evals/judge.py`'s own grading call (hardcoded to Claude regardless of `LLM_PROVIDER`) hit the
same billing error and exited uncaught — expected, since that script has no fallback by design.
**Net: the real happy path for any Anthropic-backed stage is still unverified** — this session
upgraded the known failure mode from "401 on an invalid key" to "400 on a valid key with no
credit," which is a strictly better signal (proves auth works, not just that a request is
well-formed) but still isn't a successful completion. Adding credit to that Anthropic account and
rerunning `make judge` is the single highest-value next check.

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

- **uv for Python; Docker is an optional alternative, not the default.** All Python dependency
  management, venvs and routine `make dev`/`make up` running go through `uv` (`uv sync`,
  `uv run ...`) and brew-managed services — this stays the primary workflow (faster rebuilds, no
  container overhead for day-to-day iteration). Docker was deliberately removed early in this
  project's history, then explicitly reintroduced on 2026-10-05 as a packaged alternative for
  anyone who'd rather not install four Homebrew services directly (`Dockerfile`,
  `frontend/Dockerfile`, `docker-compose.yml`, `make docker-up`/`docker-down`/`docker-ingest` —
  see the README's "Docker" section). Live-verified: built both images, brought up all six
  containers, confirmed `/api/chat` and `/api/data/overview` work against real containerized
  Neo4j/Postgres/Redis/Kafka and the bind-mounted Milvus Lite file. Keep both paths working when
  touching `Settings`/env vars — the compose file sets the same settings by service name
  (`postgres`, `redis`, `kafka`, `neo4j`) instead of `localhost`.
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
| Answer | `StubAnswerer` — canned text | `DeepAgentAnswerer` | `LLM_PROVIDER`-specific credentials (`ANTHROPIC_API_KEY`/`OPENAI_API_KEY`/always-true for `ollama`) |
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
make up          # routine dev: platform (if not running) + wait for ports + dev, one command
make lint        # ruff + mypy (src, utils, evals, tests) + tsc --noEmit
make test        # pytest — fast, offline, CI-safe, never touches a live service
make eval        # live retrieval-accuracy check against the real databases (30 questions)
make judge       # live LLM-as-a-judge run — needs ANTHROPIC_API_KEY, costs real money
make deepeval    # live DeepEval (GEval + FaithfulnessMetric) run — needs `uv sync --group eval`
make gates       # live release-gate check (retrieval + judge + deepeval + latency/cost) — needs eval group
make alerts      # live chat_audit_log alert-condition check — needs a running Postgres
make docker-up      # alternative to platform+dev: builds and starts the whole stack in containers
make docker-ingest  # like `make ingest`, but inside the api container
make docker-down    # stops the docker-compose stack
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
  mypy enforces the alias form. **`ChatOpenAI` (langchain-openai) is the opposite**: mypy wants the
  plain field name, not the alias — `model=`, not `model_name=`; `max_completion_tokens=`, not
  `max_tokens=`. `ChatOllama` (langchain-ollama) has no aliasing at all (`model=`, `base_url=`,
  `num_predict=` all match the field names) and no `timeout=` kwarg. Check `model_fields[...].alias`
  per class before trusting either convention to carry over.
- **`pymilvus` reads `MILVUS_URI` from the environment itself**, independent of our `Settings`:
  `pymilvus/settings.py` calls `load_dotenv()` and `os.getenv("MILVUS_URI", ...)` at import time,
  expecting a server address (`http://host:19530`), not a Milvus Lite file path. A `.env` that sets
  `MILVUS_URI=./data/milvus.db` (the natural name to pick) makes pymilvus's own connection
  singleton raise `ConnectionConfigException` before any of our code runs, even for calls that
  never touch that default connection. Our setting is `RIVET_MILVUS_URI` specifically to avoid
  this collision (see `src/config.py`) — don't rename it back to `MILVUS_URI`. The same
  `load_dotenv()` call is a bigger, quieter problem than just that one key: it mutates the real
  process's `os.environ` with **every** key from a developer's `.env` — API keys, `LLM_PROVIDER`,
  `USE_STUBS`, all of it — the moment `pymilvus` is imported anywhere, which happens transitively
  the instant `tests/conftest.py` pulls in `src.main`. Without a guard, a local `.env` silently
  changes which code path every test exercises (`Settings(...)` calls in tests only override the
  fields they pass explicitly; env vars fill in the rest ahead of hardcoded defaults). Fixed by
  `tests/conftest.py` neutering `dotenv.load_dotenv` *and* setting `Settings.model_config =
  SettingsConfigDict(env_file=None, ...)` (pydantic-settings does its own separate `.env`
  parsing, untouched by patching `dotenv.load_dotenv`) — both are needed, and both must happen
  before any import that could reach `pymilvus`. This is why `.env` must exist for live manual
  runs but the test suite must never assume one is absent.
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
