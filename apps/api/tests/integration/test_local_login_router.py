"""End-to-end tests for the local-admin auth path.

Since ADR-0015 D2 the local login is two steps: the password yields a signed
challenge plus a stage, and only a valid second factor yields a session. A
fresh account therefore lands in forced enrolment — there is deliberately no
way to get a session with the password alone.

Covers:
- forced enrolment on first sign-in → session+csrf cookies plus the one-time
  recovery codes, and a follow-up ``GET /auth/me`` confirming ``auth_kind``.
- the ordinary two-step sign-in once a factor exists.
- wrong-password and locked-account flows.
- ``GET /auth/capabilities`` reflects DB state.
- the login endpoints skip CSRF (they predate the session).
"""

from __future__ import annotations

import time

import pyotp
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


def _code(secret: str, *, step_offset: int = 0) -> str:
    """A TOTP code, optionally for a neighbouring 30-second step.

    Codes are single-use (``local_admins.totp_last_step``), so signing in right
    after enrolment needs the *next* step's code rather than the one just
    consumed — which is within the accepted ±1 drift, so no waiting is needed.
    """
    return pyotp.TOTP(secret, digits=6, interval=30).at(time.time() + step_offset * 30)


async def _enroll(client: AsyncClient, *, password: str) -> tuple[str, list[str]]:
    """Run the forced first sign-in. Returns (secret, recovery codes)."""
    first = await client.post("/auth/login/local", json={"username": "admin", "password": password})
    assert first.status_code == 200, first.text
    body = first.json()
    assert body["stage"] == "enroll"
    assert body["secret"] and body["qr_data_uri"].startswith("data:image/svg+xml")

    done = await client.post(
        "/auth/login/local/enroll",
        json={"challenge": body["challenge"], "code": _code(body["secret"])},
    )
    assert done.status_code == 200, done.text
    codes = done.json()["recovery_codes"]
    assert len(codes) == 10
    return body["secret"], codes


async def _sign_in(client: AsyncClient, *, password: str, secret: str) -> str:
    """Ordinary two-step sign-in once a factor exists. Returns the session id."""
    first = await client.post("/auth/login/local", json={"username": "admin", "password": password})
    assert first.status_code == 200, first.text
    assert first.json()["stage"] == "totp"
    second = await client.post(
        "/auth/login/local/totp",
        json={"challenge": first.json()["challenge"], "code": _code(secret, step_offset=1)},
    )
    assert second.status_code == 204, second.text
    sid = second.cookies.get("magister_session")
    assert sid
    return sid


class TestLoginLocal:
    async def test_password_alone_never_yields_a_session(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """The whole point of D2: no session until a second factor exists."""
        await _seed(db_session, password="hunter2hunter2")
        await db_session.commit()

        resp = await client.post(
            "/auth/login/local",
            json={"username": "admin", "password": "hunter2hunter2"},
        )
        assert resp.status_code == 200
        assert resp.cookies.get("magister_session") is None
        assert resp.json()["stage"] == "enroll"

    async def test_happy_path_issues_session_and_marks_admin(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        app_settings: Settings,
    ) -> None:
        await _seed(db_session, password="hunter2hunter2")
        await db_session.commit()

        secret, _codes = await _enroll(client, password="hunter2hunter2")
        sid = await _sign_in(client, password="hunter2hunter2", secret=secret)

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
        assert resp.status_code == 200, resp.text
        # The second step is under the same exempt prefix.
        second = await client.post(
            "/auth/login/local/enroll",
            json={"challenge": resp.json()["challenge"], "code": "000000"},
        )
        assert second.status_code == 401, second.text  # wrong code, not a CSRF rejection
