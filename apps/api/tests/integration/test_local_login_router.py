"""End-to-end tests for the local-admin auth path.

Covers:
- ``POST /auth/login/local`` happy path → session+csrf cookies, audit-event
  with no ``password`` field, and a follow-up ``GET /auth/me`` confirms the
  user is admin with ``auth_kind == "local"``.
- Wrong-password and locked-account flows.
- ``GET /auth/capabilities`` reflects DB state.
- ``POST /auth/login/local`` skips CSRF (predates session).
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from magister_api.audit.service import AuditService
from magister_api.auth.passwords import hash_password
from magister_api.config import Settings
from magister_api.models.audit import AuditEvent
from magister_api.models.auth import Session as SessionModel
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


class TestLoginLocal:
    async def test_happy_path_issues_session_and_marks_admin(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        app_settings: Settings,
    ) -> None:
        await _seed(db_session, password="hunter2hunter2")
        await db_session.commit()

        resp = await client.post(
            "/auth/login/local",
            json={"username": "admin", "password": "hunter2hunter2"},
        )
        assert resp.status_code == 204, resp.text
        sid = resp.cookies.get("magister_session")
        csrf = resp.cookies.get("magister_csrf")
        assert sid and csrf

        me = await client.get("/auth/me", cookies={"magister_session": sid})
        assert me.status_code == 200
        body = me.json()
        assert body["is_admin"] is True
        assert body["upn"] == "admin@magister.local"

        # Session row carries auth_kind="local".
        row = await db_session.execute(select(SessionModel).where(SessionModel.id == sid))
        sess = row.scalar_one()
        assert sess.auth_kind == "local"

    async def test_wrong_password_returns_401_and_audits(
        self, client: AsyncClient, db_session: AsyncSession, app_settings: Settings
    ) -> None:
        await _seed(db_session)
        await db_session.commit()

        resp = await client.post(
            "/auth/login/local",
            json={"username": "admin", "password": "definitely-wrong"},
        )
        assert resp.status_code == 401
        assert resp.json()["detail"] == "invalid_credentials"

        # Audit row exists; payload doesn't contain the password.
        rows = await db_session.execute(
            select(AuditEvent.id).where(AuditEvent.action == "local_login_failed")
        )
        ids = list(rows.scalars())
        assert len(ids) == 1
        rec = await AuditService(db_session, app_settings).read(ids[0])
        assert rec is not None and rec.payload == {"reason": "invalid_credentials"}

    async def test_lockout_after_threshold(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        await _seed(db_session)
        await db_session.commit()
        for _ in range(5):
            await client.post("/auth/login/local", json={"username": "admin", "password": "wrong"})
        # 6th attempt with the right password is locked out.
        resp = await client.post(
            "/auth/login/local",
            json={"username": "admin", "password": "secret-pw-12345"},
        )
        assert resp.status_code == 423
        assert resp.json()["detail"] == "account_locked"

    async def test_capabilities_reflects_db_state(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        # Before seed: only OIDC enabled (issuer is set in app_settings fixture).
        resp = await client.get("/auth/capabilities")
        body = resp.json()
        assert body["oidc_enabled"] is True
        assert body["local_login_enabled"] is False

        await _seed(db_session)
        await db_session.commit()

        resp = await client.get("/auth/capabilities")
        body = resp.json()
        assert body["oidc_enabled"] is True
        assert body["local_login_enabled"] is True

    async def test_login_local_is_csrf_exempt(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """The CSRF middleware exempts the /auth/login prefix."""
        await _seed(db_session, password="hunter2hunter2")
        await db_session.commit()
        # No cookie, no header — would be a CSRF rejection on any other POST.
        resp = await client.post(
            "/auth/login/local",
            json={"username": "admin", "password": "hunter2hunter2"},
        )
        assert resp.status_code == 204, resp.text
