"""Split-plan Phase 0: scheduler-owner gate + configurable DB pool.

No DB — Settings parsing and engine pool wiring are exercised offline (creating
an async engine does not open a connection).
"""

from __future__ import annotations

import pytest
from sqlalchemy.pool import NullPool, QueuePool

from magister_api import db as db_mod
from magister_api.config import Settings


def test_run_scheduler_default_on() -> None:
    # The single AD-owning container keeps the sync (AD read) loop on by default.
    assert Settings().run_scheduler is True


def test_run_scheduler_env_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MAGISTER_RUN_SCHEDULER", "0")
    assert Settings().run_scheduler is False


def test_db_pool_defaults() -> None:
    s = Settings()
    assert s.db_pool_size == 5
    assert s.db_max_overflow == 10


def test_db_pool_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MAGISTER_DB_POOL_SIZE", "3")
    monkeypatch.setenv("MAGISTER_DB_MAX_OVERFLOW", "7")
    s = Settings()
    assert s.db_pool_size == 3
    assert s.db_max_overflow == 7


@pytest.mark.asyncio
async def test_init_engine_applies_pool_size() -> None:
    engine = db_mod.init_engine(Settings(db_pool_size=7, db_max_overflow=2))
    try:
        pool = engine.pool
        assert isinstance(pool, QueuePool)  # AsyncAdaptedQueuePool subclasses it
        assert pool.size() == 7
    finally:
        await db_mod.dispose_engine()


@pytest.mark.asyncio
async def test_init_engine_poolclass_optout() -> None:
    # A caller passing its own poolclass (e.g. tests using NullPool) opts out of
    # the configured sizing without a pool_size/NullPool conflict.
    engine = db_mod.init_engine(Settings(), poolclass=NullPool)
    try:
        assert isinstance(engine.pool, NullPool)
    finally:
        await db_mod.dispose_engine()
