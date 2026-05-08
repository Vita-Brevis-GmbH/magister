"""LocalAdminService — auth/lockout/rotation/seed.

Postgres-backed because the service exercises the unique constraint and
the actual `local_admins` row, plus seeding into ``ad_user_cache`` and
``role_assignments``.
"""

from __future__ import annotations

import pytest
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from magister_api.auth.passwords import hash_password
from magister_api.config import Settings
from magister_api.models.auth import RoleAssignment
from magister_api.models.local_admin import LocalAdmin
from magister_api.repositories.local_admin import LocalAdminRepository
from magister_api.services.local_admin import (
    LOCAL_ADMIN_GUID,
    MAX_FAILED_ATTEMPTS,
    LocalAdminService,
    LoginFailed,
    LoginOk,
    LoginRefusal,
)

pytestmark = pytest.mark.postgres


async def _seed_admin(session: AsyncSession, *, password: str = "secret-pw-12345") -> LocalAdmin:
    settings = Settings(
        environment="test",  # type: ignore[arg-type]
        database_url="postgresql+asyncpg://x/y",
        audit_key="x",  # type: ignore[arg-type]
        session_secret="x",  # type: ignore[arg-type]
        csrf_secret="x",  # type: ignore[arg-type]
        local_admin_username="admin",
        local_admin_password_hash=SecretStr(hash_password(password)),
    )
    seeded = await LocalAdminService(session).seed_from_env_if_empty(settings)
    assert seeded is True
    row = await LocalAdminRepository(session).get()
    assert row is not None
    return row


class TestAuthenticate:
    async def test_happy_path_returns_admin_and_resets_counters(
        self, db_session: AsyncSession
    ) -> None:
        await _seed_admin(db_session, password="hunter2hunter2")
        result = await LocalAdminService(db_session).authenticate("admin", "hunter2hunter2")
        assert isinstance(result, LoginOk)
        assert result.admin.failed_login_count == 0
        assert result.admin.locked_until is None
        assert result.admin.last_login_at is not None

    async def test_unknown_user_returns_invalid_credentials(self, db_session: AsyncSession) -> None:
        await _seed_admin(db_session)
        result = await LocalAdminService(db_session).authenticate("nope", "wrong")
        assert isinstance(result, LoginFailed)
        assert result.reason == LoginRefusal.UNKNOWN_USER

    async def test_wrong_password_increments_counter(self, db_session: AsyncSession) -> None:
        await _seed_admin(db_session, password="hunter2hunter2")
        result = await LocalAdminService(db_session).authenticate("admin", "wrong")
        assert isinstance(result, LoginFailed)
        assert result.reason == LoginRefusal.WRONG_PASSWORD
        row = await LocalAdminRepository(db_session).get()
        assert row is not None and row.failed_login_count == 1

    async def test_account_locks_after_max_failures(self, db_session: AsyncSession) -> None:
        await _seed_admin(db_session, password="hunter2hunter2")
        svc = LocalAdminService(db_session)
        for _ in range(MAX_FAILED_ATTEMPTS):
            await svc.authenticate("admin", "wrong")
        # Even the right password is now refused while the lock holds.
        result = await svc.authenticate("admin", "hunter2hunter2")
        assert isinstance(result, LoginFailed)
        assert result.reason == LoginRefusal.LOCKED

    async def test_disabled_account_refuses_login(self, db_session: AsyncSession) -> None:
        await _seed_admin(db_session)
        await LocalAdminService(db_session).set_enabled(False)
        result = await LocalAdminService(db_session).authenticate("admin", "secret-pw-12345")
        assert isinstance(result, LoginFailed)
        assert result.reason == LoginRefusal.DISABLED


class TestLifecycle:
    async def test_change_password_rotates_hash_and_resets_counters(
        self, db_session: AsyncSession
    ) -> None:
        await _seed_admin(db_session, password="old-password-12")
        svc = LocalAdminService(db_session)
        await svc.authenticate("admin", "wrong")  # bump counter
        ok = await svc.change_password(
            current_password="old-password-12",
            new_password="brand-new-password-67",
        )
        assert ok is True
        # Old password no longer works
        bad = await svc.authenticate("admin", "old-password-12")
        assert isinstance(bad, LoginFailed)
        # New password works and counters are clean
        good = await svc.authenticate("admin", "brand-new-password-67")
        assert isinstance(good, LoginOk)
        assert good.admin.failed_login_count == 0

    async def test_change_password_rejects_wrong_current(self, db_session: AsyncSession) -> None:
        await _seed_admin(db_session, password="real-password-12")
        ok = await LocalAdminService(db_session).change_password(
            current_password="wrong",
            new_password="any-other-password-12",
        )
        assert ok is False

    async def test_set_enabled_toggles_and_clears_lock(self, db_session: AsyncSession) -> None:
        await _seed_admin(db_session)
        svc = LocalAdminService(db_session)
        for _ in range(MAX_FAILED_ATTEMPTS):
            await svc.authenticate("admin", "wrong")
        row = await svc.set_enabled(True)  # re-enabling clears the lock
        assert row is not None
        assert row.locked_until is None
        assert row.failed_login_count == 0


class TestSeed:
    async def test_seed_creates_admin_role_row_for_sentinel_guid(
        self, db_session: AsyncSession
    ) -> None:
        await _seed_admin(db_session)
        result = await db_session.execute(
            select(RoleAssignment).where(RoleAssignment.ad_object_guid == LOCAL_ADMIN_GUID)
        )
        rows = list(result.scalars())
        assert len(rows) == 1
        assert rows[0].role == "admin"
        assert rows[0].school_id is None
        assert rows[0].granted_by == "bootstrap"

    async def test_seed_is_idempotent(self, db_session: AsyncSession) -> None:
        await _seed_admin(db_session)
        # Second seed call must NOT create another row, and must NOT raise.
        settings = Settings(
            environment="test",  # type: ignore[arg-type]
            database_url="postgresql+asyncpg://x/y",
            audit_key="x",  # type: ignore[arg-type]
            session_secret="x",  # type: ignore[arg-type]
            csrf_secret="x",  # type: ignore[arg-type]
            local_admin_username="admin",
            local_admin_password_hash=SecretStr(hash_password("anything-12345")),
        )
        seeded = await LocalAdminService(db_session).seed_from_env_if_empty(settings)
        assert seeded is False

    async def test_seed_refuses_plaintext_password_hash(self, db_session: AsyncSession) -> None:
        settings = Settings(
            environment="test",  # type: ignore[arg-type]
            database_url="postgresql+asyncpg://x/y",
            audit_key="x",  # type: ignore[arg-type]
            session_secret="x",  # type: ignore[arg-type]
            csrf_secret="x",  # type: ignore[arg-type]
            local_admin_username="admin",
            local_admin_password_hash=SecretStr("plaintext-not-a-hash"),
        )
        seeded = await LocalAdminService(db_session).seed_from_env_if_empty(settings)
        assert seeded is False
        assert await LocalAdminRepository(db_session).get() is None
