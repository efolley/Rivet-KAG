"""Mini test suite for the Phase 3 platform wiring: Redis response caching, and that chat keeps
working when Postgres or Redis is unavailable. Kafka failures are tested at the client level
(publish_event itself never raises) rather than through the route, since the route can't
observe a difference either way — that's the point.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.clients.kafka import publish_event
from src.db import ChatAuditLog
from src.main import app
from src.schemas import ChatResponse

client = TestClient(app)


async def test_chat_serves_a_cached_response_without_rerunning_the_pipeline(
    monkeypatch: pytest.MonkeyPatch, db_session: object
) -> None:
    cached = ChatResponse(answer="cached answer text", citations=[], trace=[])

    async def fake_get_cached(key: str) -> ChatResponse:
        return cached

    async def boom(*args: object, **kwargs: object) -> None:
        raise AssertionError("the pipeline should not run on a cache hit")

    monkeypatch.setattr("src.api.routes.chat._get_cached", fake_get_cached)
    monkeypatch.setattr("src.pipeline.orchestrator.Pipeline.run", boom)

    r = client.post("/api/chat", json={"session_id": "s1", "message": "any question"})

    assert r.status_code == 200
    assert r.json()["answer"] == "cached answer text"


def test_chat_still_responds_when_postgres_is_unreachable(broken_db_session: object) -> None:
    r = client.post("/api/chat", json={"session_id": "s1", "message": "Who is on the data team?"})
    assert r.status_code == 200
    assert r.json()["answer"]


def test_chat_still_responds_when_redis_is_unreachable(monkeypatch: pytest.MonkeyPatch, db_session: object) -> None:
    class BrokenRedis:
        async def get(self, key: str) -> None:
            raise ConnectionError("redis is unreachable (simulated)")

        async def set(self, *args: object, **kwargs: object) -> None:
            raise ConnectionError("redis is unreachable (simulated)")

    monkeypatch.setattr("src.api.routes.chat.get_redis", lambda: BrokenRedis())

    r = client.post("/api/chat", json={"session_id": "s1", "message": "Who is on the data team?"})

    assert r.status_code == 200
    assert r.json()["answer"]


async def test_chat_records_total_cost_usd_in_the_audit_log(db_session: AsyncSession) -> None:
    # Stub pipeline makes no LLM call, so total_cost_usd is genuinely None (no stage priced) --
    # this confirms the column round-trips end to end (ChatResponse -> ChatAuditLog), not any
    # particular value. See src/db/models.py's ChatAuditLog.cost_usd and evals/check_alerts.py,
    # which this column exists to feed.
    r = client.post("/api/chat", json={"session_id": "cost-audit-test", "message": "Who is on the data team?"})
    assert r.status_code == 200

    result = await db_session.execute(
        select(ChatAuditLog).where(ChatAuditLog.session_id == "cost-audit-test")
    )
    row = result.scalar_one()
    assert row.cost_usd == r.json()["total_cost_usd"]


async def test_chat_forces_a_free_response_when_the_session_is_over_its_daily_cap(
    monkeypatch: pytest.MonkeyPatch, db_session: AsyncSession
) -> None:
    captured: dict[str, object] = {}

    async def fake_spend(db: object, session_id: str) -> float:
        return 5.00  # above SESSION_DAILY_BUDGET_USD ($1.00)

    async def fake_run(self: object, req: object, max_answer_cost_usd: float | None = None) -> ChatResponse:
        captured["max_answer_cost_usd"] = max_answer_cost_usd
        return ChatResponse(answer="ok", citations=[], trace=[])

    monkeypatch.setattr("src.api.routes.chat._session_spend_24h", fake_spend)
    monkeypatch.setattr("src.pipeline.orchestrator.Pipeline.run", fake_run)

    r = client.post("/api/chat", json={"session_id": "over-budget", "message": "any question"})

    assert r.status_code == 200
    assert captured["max_answer_cost_usd"] == 0.0


async def test_chat_uses_the_default_budget_when_the_session_is_under_its_cap(
    monkeypatch: pytest.MonkeyPatch, db_session: AsyncSession
) -> None:
    captured: dict[str, object] = {}

    async def fake_spend(db: object, session_id: str) -> float:
        return 0.02  # well under SESSION_DAILY_BUDGET_USD

    async def fake_run(self: object, req: object, max_answer_cost_usd: float | None = None) -> ChatResponse:
        captured["max_answer_cost_usd"] = max_answer_cost_usd
        return ChatResponse(answer="ok", citations=[], trace=[])

    monkeypatch.setattr("src.api.routes.chat._session_spend_24h", fake_spend)
    monkeypatch.setattr("src.pipeline.orchestrator.Pipeline.run", fake_run)

    r = client.post("/api/chat", json={"session_id": "under-budget", "message": "any question"})

    assert r.status_code == 200
    assert captured["max_answer_cost_usd"] is None


async def test_chat_does_not_block_when_session_spend_cannot_be_checked(
    monkeypatch: pytest.MonkeyPatch, db_session: AsyncSession
) -> None:
    # None means "couldn't check" (e.g. Postgres down) -- must behave like "under budget", not
    # like "over budget", so a platform outage can never cut off real users' answers.
    captured: dict[str, object] = {}

    async def fake_spend(db: object, session_id: str) -> None:
        return None

    async def fake_run(self: object, req: object, max_answer_cost_usd: float | None = None) -> ChatResponse:
        captured["max_answer_cost_usd"] = max_answer_cost_usd
        return ChatResponse(answer="ok", citations=[], trace=[])

    monkeypatch.setattr("src.api.routes.chat._session_spend_24h", fake_spend)
    monkeypatch.setattr("src.pipeline.orchestrator.Pipeline.run", fake_run)

    r = client.post("/api/chat", json={"session_id": "unknown-budget", "message": "any question"})

    assert r.status_code == 200
    assert captured["max_answer_cost_usd"] is None


async def test_publish_event_swallows_a_broken_producer(monkeypatch: pytest.MonkeyPatch) -> None:
    class BrokenProducer:
        async def start(self) -> None:
            raise ConnectionError("kafka is unreachable (simulated)")

    monkeypatch.setattr("src.clients.kafka._producer", lambda: BrokenProducer())
    monkeypatch.setattr("src.clients.kafka._started", False)

    await publish_event("rivet.test", {"hello": "world"})  # must not raise
