"""Engine pro Mandant (ADR-0013 D1).

Ein Eintrag der Registry trägt DSN plus Schema; hier wird daraus eine Engine.
Der Schlüssel ist der **DSN**, nicht der Slug: mehrere Mandanten im selben
Cluster mit derselben Anmelderolle würden sich eine Engine teilen — was die
Registry ab zwei Mandanten gerade verbietet, weshalb in der Praxis jeder
Mandant seine eigene Engine und damit seinen eigenen Verbindungs-Pool hat.

Das ist der Preis der harten Trennung, und er ist rechenbar: Verbindungen =
Mandanten × Prozesse × (pool_size + max_overflow). Deshalb sind die
Mandanten-Pools klein voreingestellt (``MAGISTER_TENANT_POOL_SIZE``) und
deutlich kleiner als der eine grosse Pool von vorher — bei vielen Mandanten
gehört ein PgBouncer davor.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from magister_api.tenancy.registry import Tenant

logger = logging.getLogger(__name__)


class TenantEngineRegistry:
    """Engines und Session-Fabriken je DSN, einmal gebaut und dann gehalten."""

    def __init__(
        self,
        *,
        pool_size: int,
        max_overflow: int,
        engine_kwargs: dict[str, Any] | None = None,
    ) -> None:
        self._pool_size = pool_size
        self._max_overflow = max_overflow
        self._engine_kwargs = engine_kwargs or {}
        self._engines: dict[str, AsyncEngine] = {}
        self._sessionmakers: dict[str, async_sessionmaker[AsyncSession]] = {}

    def engine_for(self, tenant: Tenant) -> AsyncEngine:
        engine = self._engines.get(tenant.dsn)
        if engine is None:
            kwargs: dict[str, Any] = dict(self._engine_kwargs)
            if "poolclass" not in kwargs and "pool_size" not in kwargs:
                kwargs["pool_size"] = self._pool_size
                kwargs["max_overflow"] = self._max_overflow
            engine = create_async_engine(tenant.dsn, pool_pre_ping=True, future=True, **kwargs)
            self._engines[tenant.dsn] = engine
            # Kein DSN im Log: er trägt den Anmeldenamen und je nach Ablage ein
            # Passwort. Der Slug genügt, um die Zeile zuzuordnen.
            logger.info("Engine für Mandant %s aufgebaut", tenant.slug)
        return engine

    def sessionmaker_for(self, tenant: Tenant) -> async_sessionmaker[AsyncSession]:
        sm = self._sessionmakers.get(tenant.dsn)
        if sm is None:
            sm = async_sessionmaker(
                self.engine_for(tenant), expire_on_commit=False, autoflush=False
            )
            self._sessionmakers[tenant.dsn] = sm
        return sm

    async def dispose_all(self) -> None:
        for dsn, engine in list(self._engines.items()):
            await engine.dispose()
            self._engines.pop(dsn, None)
            self._sessionmakers.pop(dsn, None)
