"""Shared fixtures. `db_session` stands in for Postgres with a real, in-memory SQLite database
(via FastAPI's dependency_overrides) — genuine CRUD behavior, no live Postgres required, in
keeping with this project's "tests never need a live service" rule.
"""

import dotenv

# pymilvus's own settings.py calls load_dotenv() at import time (see CLAUDE.md's known gotchas),
# which mutates the real process environment with every key in a developer's .env -- API keys,
# LLM_PROVIDER, USE_STUBS, all of it -- not just the Milvus-related ones. That import happens
# transitively the moment this conftest pulls in src.main below, so without neutering it first,
# a local .env silently changes which code path every test exercises (env vars beat a bare
# Settings(...) call's hardcoded defaults for every field the test didn't pass explicitly).
# This must run before any import below that could reach pymilvus.
dotenv.load_dotenv = lambda *args, **kwargs: False  # type: ignore[assignment]

from collections.abc import AsyncGenerator  # noqa: E402
from typing import Any  # noqa: E402

import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402
from pydantic_settings import SettingsConfigDict  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from src.config import Settings  # noqa: E402
from src.db import Base  # noqa: E402
from src.db.engine import get_session  # noqa: E402
from src.main import app  # noqa: E402

# Separately, pydantic-settings does its own .env parsing (not via dotenv.load_dotenv, so the
# patch above doesn't touch it) and would otherwise fill in every field a test didn't pass
# explicitly from the real .env. Disable that source too, so `Settings(...)` in tests only ever
# sees its hardcoded defaults plus whatever a test passes.
Settings.model_config = SettingsConfigDict(env_file=None, extra="ignore")


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
