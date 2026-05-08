"""Lifespan seeds the local-admin row from env on first boot."""

from __future__ import annotations

import pytest
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession

from magister_api.auth.passwords import hash_password
from magister_api.config import Settings
from magister_api.models.local_admin import LocalAdmin
from magister_api.repositories.local_admin import LocalAdminRepository
from magister_api.services.local_admin import LocalAdminService

pytestmark = pytest.mark.postgres


def _seed_settings(*, password: str = "lifespan-test-12") -> Settings:
    return Settings(
        environment="test",  # type: ignore[arg-type]
        database_url="postgresql+asyncpg://x/y",
        audit_key="x",  # type: ignore[arg-type]
        session_secret="x",  # type: ignore[arg-type]
        csrf_secret="x",  # type: ignore[arg-type]
        local_admin_username="ops",
        local_admin_password_hash=SecretStr(hash_password(password)),
    )


class TestLifespanSeed:
    async def test_seeds_when_table_is_empty(self, db_session: AsyncSession) -> None:
        await LocalAdminService(db_session).seed_from_env_if_empty(_seed_settings())
        row = await LocalAdminRepository(db_session).get()
        assert row is not None
        assert row.username == "ops"
        assert row.enabled is True

    async def test_second_call_is_a_no_op(self, db_session: AsyncSession) -> None:
        svc = LocalAdminService(db_session)
        first = await svc.seed_from_env_if_empty(_seed_settings(password="first-time-pw-12"))
        await db_session.commit()
        # Use a different password in the second call to prove it does NOT
        # overwrite the existing row.
        second = await svc.seed_from_env_if_empty(_seed_settings(password="other-pw-1234567"))
        assert first is True
        assert second is False
        # The original row remains intact.
        row = await LocalAdminRepository(db_session).get()
        assert row is not None
        assert isinstance(row, LocalAdmin)

    async def test_no_op_when_env_unset(self, db_session: AsyncSession) -> None:
        settings = Settings(
            environment="test",  # type: ignore[arg-type]
            database_url="postgresql+asyncpg://x/y",
            audit_key="x",  # type: ignore[arg-type]
            session_secret="x",  # type: ignore[arg-type]
            csrf_secret="x",  # type: ignore[arg-type]
            local_admin_username="",
            local_admin_password_hash=None,
        )
        seeded = await LocalAdminService(db_session).seed_from_env_if_empty(settings)
        assert seeded is False
        assert await LocalAdminRepository(db_session).get() is None
