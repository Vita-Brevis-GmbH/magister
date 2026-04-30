"""Async SQLAlchemy engine + session factory."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Any

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from magister_api.config import Settings, get_settings

_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def init_engine(settings: Settings | None = None, **engine_kwargs: Any) -> AsyncEngine:
    """Initialise the global async engine. Called once on app startup."""
    global _engine, _sessionmaker
    s = settings or get_settings()
    _engine = create_async_engine(
        s.database_url,
        pool_pre_ping=True,
        future=True,
        **engine_kwargs,
    )
    _sessionmaker = async_sessionmaker(_engine, expire_on_commit=False, autoflush=False)
    return _engine


def get_engine() -> AsyncEngine:
    if _engine is None:
        init_engine()
    assert _engine is not None
    return _engine


def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    if _sessionmaker is None:
        init_engine()
    assert _sessionmaker is not None
    return _sessionmaker


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency: one auto-committed transaction per request.

    The session relies on SQLAlchemy 2.x autobegin: the first DB op opens a
    transaction; the wrapper commits on success and rolls back on exception.
    Service code therefore should NOT call ``session.commit()`` or
    ``session.begin()`` — that's the request handler's contract.
    """
    sm = get_sessionmaker()
    async with sm() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        else:
            await session.commit()


async def dispose_engine() -> None:
    global _engine, _sessionmaker
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _sessionmaker = None
