"""Shared fixtures. `db_session` stands in for Postgres with a real, in-memory SQLite database
(via FastAPI's dependency_overrides) — genuine CRUD behavior, no live Postgres required, in
keeping with this project's "tests never need a live service" rule.
"""

from collections.abc import AsyncGenerator
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from src.db import Base
from src.db.engine import get_session
from src.main import app


@pytest.fixture(autouse=True)
def _no_real_kafka(monkeypatch: pytest.MonkeyPatch) -> None:
    """Applies to every test: /api/chat publishes a Kafka event on success, and without this,
    the first test to hit that path for real starts a module-cached AIOKafkaProducer bound to
    *that test's* event loop. pytest-asyncio gives every test function its own event loop, so
    any later test reusing the same cached producer hangs forever awaiting a future that
    belongs to a closed loop — invisible in production, where uvicorn keeps one event loop for
    the app's whole lifetime. Tests that want the real publish_event (e.g. to test its own
    failure handling) call it directly, bypassing this patch on the route.
    """

    async def noop(topic: str, payload: dict[str, Any]) -> None:
        return None

    monkeypatch.setattr("src.api.routes.chat.publish_event", noop)


@pytest_asyncio.fixture
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:", poolclass=StaticPool, connect_args={"check_same_thread": False}
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    sessionmaker = async_sessionmaker(engine, expire_on_commit=False)

    async def override_get_session() -> AsyncGenerator[AsyncSession, None]:
        async with sessionmaker() as session:
            yield session

    app.dependency_overrides[get_session] = override_get_session
    try:
        async with sessionmaker() as session:
            yield session
    finally:
        app.dependency_overrides.pop(get_session, None)
        await engine.dispose()


@pytest_asyncio.fixture
async def broken_db_session() -> AsyncGenerator[None, None]:
    """Points get_session at an unreachable Postgres — like production, the engine/session
    construct lazily without erroring; the connection attempt only happens on first query
    (inside a route's own try/except), which is exactly what this fixture is for testing.
    """
    bad_engine = create_async_engine("postgresql+asyncpg://nouser:nopass@localhost:1/nodb")
    sessionmaker = async_sessionmaker(bad_engine, expire_on_commit=False)

    async def override_get_session() -> AsyncGenerator[AsyncSession, None]:
        async with sessionmaker() as session:
            yield session

    app.dependency_overrides[get_session] = override_get_session
    try:
        yield
    finally:
        app.dependency_overrides.pop(get_session, None)
        await bad_engine.dispose()
