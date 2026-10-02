"""Async SQLAlchemy engine/session setup. No stub variant: unlike the LLM pipeline stages,
there's no meaningful "fake Postgres" — code that touches the DB is written to degrade
gracefully (see chat.py, files.py) instead.
"""

from collections.abc import AsyncGenerator
from functools import lru_cache

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from src.config import get_settings
from src.db.models import Base


@lru_cache
def get_engine() -> AsyncEngine:
    return create_async_engine(get_settings().database_url)


@lru_cache
def _sessionmaker() -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(get_engine(), expire_on_commit=False)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    async with _sessionmaker()() as session:
        yield session


async def init_db() -> None:
    """Create tables if they don't exist yet. Called best-effort on app startup (see main.py)."""
    async with get_engine().begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
