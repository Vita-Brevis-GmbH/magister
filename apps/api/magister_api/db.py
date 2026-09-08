"""Async SQLAlchemy engine + session factory.

The request-scoped session is **tenant-scoped** (ADR-0013 D1): which engine it
comes from and which schema it sees is decided by the tenant the resolution
middleware put on the request. That is why ``get_session`` takes a ``Request``
— and why every router could stay untouched: they all depend on
``Depends(get_session)`` and never on the engine.

``init_engine``/``get_sessionmaker`` remain for the processes that have no
request to resolve from: the startup seeds, the AD-sync scheduler and the CLI.
Those run against ``database_url`` and are single-tenant by nature; the
per-tenant fan-out for them comes with the console in Phase 2.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Any

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from starlette.requests import Request

from magister_api.config import Settings, get_settings
from magister_api.tenancy.context import get_engines, tenant_from_request
from magister_api.tenancy.scope import apply_tenant_scope

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


async def get_session(request: Request) -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency: one auto-committed, tenant-scoped transaction.

    The session relies on SQLAlchemy 2.x autobegin: the first DB op opens a
    transaction; the wrapper commits on success and rolls back on exception.
    Service code therefore should NOT call ``session.commit()`` or
    ``session.begin()`` — that's the request handler's contract.

    The first DB op is ours: ``apply_tenant_scope`` sets the search_path and
    verifies against the database that this transaction really is the tenant's,
    before any handler code runs. A failure there aborts the request rather
    than serving a query whose scope nobody checked.
    """
    tenant = tenant_from_request(request)
    settings: Settings = request.app.state.settings
    sm = get_engines().sessionmaker_for(tenant)
    async with sm() as session:
        try:
            await apply_tenant_scope(session, tenant, extension_schema=settings.extension_schema)
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
