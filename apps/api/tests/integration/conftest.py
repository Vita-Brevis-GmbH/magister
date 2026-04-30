"""Integration-test conftest.

Skip cleanly if ``MAGISTER_TEST_DATABASE_URL`` is not set. Otherwise create a
fresh schema (drop+create_all) and seed pgcrypto for each test session.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from magister_api.models import Base


def _url() -> str | None:
    return os.environ.get("MAGISTER_TEST_DATABASE_URL")


@pytest.fixture(scope="session")
def database_url() -> str:
    url = _url()
    if not url:
        pytest.skip("MAGISTER_TEST_DATABASE_URL not set")
    return url


@pytest_asyncio.fixture(scope="session")
async def engine(database_url: str) -> AsyncIterator[AsyncEngine]:
    eng = create_async_engine(database_url, future=True, pool_pre_ping=True)
    async with eng.begin() as conn:
        await conn.exec_driver_sql("CREATE EXTENSION IF NOT EXISTS pgcrypto")
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
        # Mirror the partial-unique index the Alembic migration adds.
        await conn.exec_driver_sql(
            "CREATE UNIQUE INDEX IF NOT EXISTS ix_role_assignments_admin_unique "
            "ON role_assignments (ad_object_guid, role) "
            "WHERE school_id IS NULL AND revoked_at IS NULL"
        )
    yield eng
    await eng.dispose()


@pytest_asyncio.fixture
async def db_session(engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    """Per-test session that wraps everything in a transaction and rolls back at the end."""
    sm = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
    async with engine.connect() as conn:
        trans = await conn.begin()
        async with sm(bind=conn) as session:
            try:
                yield session
            finally:
                await trans.rollback()
