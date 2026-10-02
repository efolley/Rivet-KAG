"""Mini test suite for the Phase 3 platform wiring: Redis response caching, and that chat keeps
working when Postgres or Redis is unavailable. Kafka failures are tested at the client level
(publish_event itself never raises) rather than through the route, since the route can't
observe a difference either way — that's the point.
"""

import pytest
from fastapi.testclient import TestClient

from src.clients.kafka import publish_event
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


async def test_publish_event_swallows_a_broken_producer(monkeypatch: pytest.MonkeyPatch) -> None:
    class BrokenProducer:
        async def start(self) -> None:
            raise ConnectionError("kafka is unreachable (simulated)")

    monkeypatch.setattr("src.clients.kafka._producer", lambda: BrokenProducer())
    monkeypatch.setattr("src.clients.kafka._started", False)

    await publish_event("rivet.test", {"hello": "world"})  # must not raise
