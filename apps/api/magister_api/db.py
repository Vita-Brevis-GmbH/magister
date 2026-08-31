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
    """Initialise the global async engine. Called once on app startup.

    Pool size comes from settings (``db_pool_size``/``db_max_overflow``) so a
    per-function container split can cap each process's connection footprint
    against the shared Postgres. A caller that passes its own ``poolclass`` or
    ``pool_size`` (e.g. tests using ``NullPool``) opts out of the sizing.
    """
    global _engine, _sessionmaker
    s = settings or get_settings()
    pool_kwargs: dict[str, Any] = {}
    if "poolclass" not in engine_kwargs and "pool_size" not in engine_kwargs:
        pool_kwargs = {"pool_size": s.db_pool_size, "max_overflow": s.db_max_overflow}
    _engine = create_async_engine(
        s.database_url,
        pool_pre_ping=True,
        future=True,
        **pool_kwargs,
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
