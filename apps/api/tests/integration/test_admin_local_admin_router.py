"""Admin-only lifecycle endpoints under ``/admin/local-admin``."""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession

from magister_api.auth.passwords import hash_password
from magister_api.config import Settings
from magister_api.repositories.local_admin import LocalAdminRepository
from magister_api.services.local_admin import LocalAdminService

pytestmark = pytest.mark.postgres


async def _seed(session: AsyncSession, *, password: str = "secret-pw-12345") -> None:
    settings = Settings(
        environment="test",  # type: ignore[arg-type]
        database_url="postgresql+asyncpg://x/y",
        audit_key="x",  # type: ignore[arg-type]
        session_secret="x",  # type: ignore[arg-type]
        csrf_secret="x",  # type: ignore[arg-type]
        local_admin_username="admin",
        local_admin_password_hash=SecretStr(hash_password(password)),
    )
    await LocalAdminService(session).seed_from_env_if_empty(settings)


class TestRequiresAdmin:
    async def test_get_status_rejects_anonymous(self, client: AsyncClient) -> None:
        resp = await client.get("/admin/local-admin")
        assert resp.status_code == 401

    async def test_password_change_rejects_schulleitung(
        self, as_schulleitung_a: AsyncClient, db_session: AsyncSession
    ) -> None:
        await _seed(db_session)
        await db_session.commit()
        resp = await as_schulleitung_a.post(
            "/admin/local-admin/password",
            json={"current_password": "secret-pw-12345", "new_password": "another-one-12"},
        )
        assert resp.status_code == 403


class TestPasswordChange:
    async def test_happy_path_rotates_hash(
        self,
        as_admin: AsyncClient,
        db_session: AsyncSession,
    ) -> None:
        await _seed(db_session, password="old-password-12")
        await db_session.commit()
        resp = await as_admin.post(
            "/admin/local-admin/password",
            json={
                "current_password": "old-password-12",
                "new_password": "new-password-678",
            },
        )
        assert resp.status_code == 204, resp.text
        # New password works for login
        login = await as_admin.post(
            "/auth/login/local",
            json={"username": "admin", "password": "new-password-678"},
        )
        assert login.status_code == 204

    async def test_wrong_current_password_returns_400(
        self, as_admin: AsyncClient, db_session: AsyncSession
    ) -> None:
        await _seed(db_session, password="real-password-12")
        await db_session.commit()
        resp = await as_admin.post(
            "/admin/local-admin/password",
            json={"current_password": "wrong", "new_password": "any-other-pw-1"},
        )
        assert resp.status_code == 400
        assert resp.json()["detail"] == "invalid_current_password"


class TestEnabledToggle:
    async def test_admin_can_disable_local_admin(
        self, as_admin: AsyncClient, db_session: AsyncSession
    ) -> None:
        await _seed(db_session)
        await db_session.commit()
        resp = await as_admin.patch("/admin/local-admin", json={"enabled": False})
        assert resp.status_code == 200
        assert resp.json()["enabled"] is False
        # Login is now refused with 403 disabled
        login = await as_admin.post(
            "/auth/login/local",
            json={"username": "admin", "password": "secret-pw-12345"},
        )
        assert login.status_code == 403
        assert login.json()["detail"] == "local_login_disabled"

    async def test_re_enabling_clears_lockout(
        self, as_admin: AsyncClient, db_session: AsyncSession
    ) -> None:
        await _seed(db_session)
        # Push the row into a locked state directly.
        admin = await LocalAdminRepository(db_session).get()
        assert admin is not None
        from datetime import UTC, datetime, timedelta

        admin.locked_until = datetime.now(UTC) + timedelta(minutes=15)
        admin.failed_login_count = 5
        await db_session.commit()

        resp = await as_admin.patch("/admin/local-admin", json={"enabled": True})
        assert resp.status_code == 200
        body = resp.json()
        assert body["locked_until"] is None
