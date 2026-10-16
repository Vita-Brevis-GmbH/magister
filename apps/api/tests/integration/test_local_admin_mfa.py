"""Second factor of the local break-glass account, end to end (ADR-0015 D2).

Two properties get their own tests because the whole design rests on them:

- a code is single-use, and wrong codes hit the same lockout as wrong passwords;
- a reset never returns a secret, so an operator cannot mint a working factor.
"""

from __future__ import annotations

import time

import pyotp
import pytest
from httpx import AsyncClient
from pydantic import SecretStr
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from magister_api.audit.service import AuditService
from magister_api.auth.passwords import hash_password
from magister_api.config import Settings
from magister_api.models.audit import AuditEvent
from magister_api.models.base import utcnow
from magister_api.models.local_admin import LocalAdmin
from magister_api.services.local_admin import LocalAdminService
from magister_api.services.local_admin_mfa import MFA_SUSPENSION

pytestmark = pytest.mark.postgres

PASSWORD = "secret-pw-12345"  # noqa: S105 — test fixture, not a credential


async def _seed(session: AsyncSession) -> None:
    settings = Settings(
        environment="test",  # type: ignore[arg-type]
        database_url="postgresql+asyncpg://x/y",
        audit_key="x",  # type: ignore[arg-type]
        session_secret="x",  # type: ignore[arg-type]
        csrf_secret="x",  # type: ignore[arg-type]
        local_admin_username="admin",
        local_admin_password_hash=SecretStr(hash_password(PASSWORD)),
    )
    await LocalAdminService(session).seed_from_env_if_empty(settings)


def _code(secret: str, *, step_offset: int = 0) -> str:
    # int(): pyotp.at() nimmt int oder datetime, time.time() liefert float.
    return pyotp.TOTP(secret, digits=6, interval=30).at(int(time.time()) + step_offset * 30)


async def _enroll(client: AsyncClient) -> tuple[str, list[str]]:
    first = await client.post("/auth/login/local", json={"username": "admin", "password": PASSWORD})
    body = first.json()
    assert body["stage"] == "enroll"
    done = await client.post(
        "/auth/login/local/enroll",
        json={"challenge": body["challenge"], "code": _code(body["secret"])},
    )
    assert done.status_code == 200, done.text
    return body["secret"], done.json()["recovery_codes"]


async def _challenge(client: AsyncClient, *, stage: str = "totp") -> str:
    resp = await client.post("/auth/login/local", json={"username": "admin", "password": PASSWORD})
    assert resp.status_code == 200, resp.text
    assert resp.json()["stage"] == stage
    return resp.json()["challenge"]


class TestSecondFactorVerification:
    async def test_a_code_cannot_be_replayed(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        await _seed(db_session)
        await db_session.commit()
        secret, _ = await _enroll(client)

        code = _code(secret, step_offset=1)
        first = await client.post(
            "/auth/login/local/totp", json={"challenge": await _challenge(client), "code": code}
        )
        assert first.status_code == 204, first.text

        again = await client.post(
            "/auth/login/local/totp", json={"challenge": await _challenge(client), "code": code}
        )
        assert again.status_code == 401
        assert again.json()["detail"] == "invalid_code"

    async def test_recovery_code_works_once(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        await _seed(db_session)
        await db_session.commit()
        _secret, codes = await _enroll(client)

        used = codes[0]
        ok = await client.post(
            "/auth/login/local/totp", json={"challenge": await _challenge(client), "code": used}
        )
        assert ok.status_code == 204, ok.text
        assert ok.cookies.get("magister_session")

        again = await client.post(
            "/auth/login/local/totp", json={"challenge": await _challenge(client), "code": used}
        )
        assert again.status_code == 401

        # A different code from the same set still works.
        other = await client.post(
            "/auth/login/local/totp",
            json={"challenge": await _challenge(client), "code": codes[1]},
        )
        assert other.status_code == 204, other.text

    async def test_wrong_codes_trip_the_account_lockout(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """A stolen password must not buy unlimited guesses at the second factor."""
        await _seed(db_session)
        await db_session.commit()
        await _enroll(client)

        for _ in range(5):
            resp = await client.post(
                "/auth/login/local/totp",
                json={"challenge": await _challenge(client), "code": "000000"},
            )
            assert resp.status_code == 401

        locked = await client.post(
            "/auth/login/local", json={"username": "admin", "password": PASSWORD}
        )
        assert locked.status_code == 423
        assert locked.json()["detail"] == "account_locked"

    async def test_expired_challenge_is_refused(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        await _seed(db_session)
        await db_session.commit()
        secret, _ = await _enroll(client)

        resp = await client.post(
            "/auth/login/local/totp",
            json={"challenge": "not-a-real.challenge", "code": _code(secret, step_offset=1)},
        )
        assert resp.status_code == 401
        assert resp.json()["detail"] == "expired"


class TestResetActions:
    async def test_reset_forces_enrollment_and_returns_no_secret(
        self,
        client: AsyncClient,
        as_admin: AsyncClient,
        db_session: AsyncSession,
        app_settings: Settings,
    ) -> None:
        await _seed(db_session)
        await db_session.commit()
        await _enroll(client)

        resp = await as_admin.delete("/admin/local-admin/mfa")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["enrolled"] is False
        assert body["recovery_codes_left"] == 0
        assert body["reset_by"] == "admin@example.ch"
        # Nothing secret comes back — that is the point.
        assert "secret" not in body and "recovery_codes" not in body

        # The next sign-in is forced through enrolment again.
        await _challenge(client, stage="enroll")

        rows = await db_session.execute(
            select(AuditEvent.id).where(AuditEvent.action == "local_totp_reset")
        )
        ids = list(rows.scalars())
        assert len(ids) == 1
        rec = await AuditService(db_session, app_settings).read(ids[0])
        assert rec is not None and rec.payload == {"forces_enrollment": True}

    async def test_regenerate_recovery_codes_keeps_the_secret(
        self, client: AsyncClient, as_admin: AsyncClient, db_session: AsyncSession
    ) -> None:
        await _seed(db_session)
        await db_session.commit()
        secret, old_codes = await _enroll(client)

        resp = await as_admin.post("/admin/local-admin/mfa/recovery-codes")
        assert resp.status_code == 200, resp.text
        new_codes = resp.json()["recovery_codes"]
        assert len(new_codes) == 10
        assert set(new_codes).isdisjoint(old_codes)

        # An old code no longer works …
        stale = await client.post(
            "/auth/login/local/totp",
            json={"challenge": await _challenge(client), "code": old_codes[0]},
        )
        assert stale.status_code == 401
        # … but the TOTP secret is untouched.
        ok = await client.post(
            "/auth/login/local/totp",
            json={"challenge": await _challenge(client), "code": _code(secret, step_offset=1)},
        )
        assert ok.status_code == 204, ok.text

    async def test_regenerate_refuses_when_not_enrolled(
        self, as_admin: AsyncClient, db_session: AsyncSession
    ) -> None:
        await _seed(db_session)
        await db_session.commit()
        resp = await as_admin.post("/admin/local-admin/mfa/recovery-codes")
        assert resp.status_code == 409
        assert resp.json()["detail"] == "mfa_not_enrolled"

    async def test_suspension_lets_the_password_alone_through_and_expires(
        self, client: AsyncClient, as_admin: AsyncClient, db_session: AsyncSession
    ) -> None:
        await _seed(db_session)
        await db_session.commit()
        await _enroll(client)

        resp = await as_admin.post(
            "/admin/local-admin/mfa/suspend", json={"reason": "VB-2291 Telefon verloren"}
        )
        assert resp.status_code == 200, resp.text
        until = resp.json()["suspended_until"]
        assert until is not None

        # Password alone now yields a session.
        bypass = await client.post(
            "/auth/login/local", json={"username": "admin", "password": PASSWORD}
        )
        assert bypass.status_code == 204, bypass.text
        assert bypass.cookies.get("magister_session")

        # Wind the clock past the window: the requirement is back, untouched.
        await db_session.execute(
            update(LocalAdmin)
            .where(LocalAdmin.id == 1)
            .values(mfa_suspended_until=utcnow() - MFA_SUSPENSION)
        )
        await db_session.commit()
        await _challenge(client, stage="totp")

    async def test_suspension_is_audited_with_the_reason(
        self,
        client: AsyncClient,
        as_admin: AsyncClient,
        db_session: AsyncSession,
        app_settings: Settings,
    ) -> None:
        await _seed(db_session)
        await db_session.commit()
        await _enroll(client)
        await as_admin.post("/admin/local-admin/mfa/suspend", json={"reason": "VB-2291"})

        rows = await db_session.execute(
            select(AuditEvent.id).where(AuditEvent.action == "local_mfa_requirement_suspended")
        )
        ids = list(rows.scalars())
        assert len(ids) == 1
        rec = await AuditService(db_session, app_settings).read(ids[0])
        assert rec is not None
        assert rec.payload["reason"] == "VB-2291"
        assert rec.payload["until"]

    async def test_status_surface_hides_every_secret(
        self, client: AsyncClient, as_admin: AsyncClient, db_session: AsyncSession
    ) -> None:
        await _seed(db_session)
        await db_session.commit()
        await _enroll(client)

        resp = await as_admin.get("/admin/local-admin/mfa")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body == {
            "enrolled": True,
            "recovery_codes_left": 10,
            "reset_at": None,
            "reset_by": None,
            "suspended_until": None,
        }


class TestAuditNeverCarriesTheFactor:
    async def test_enrolment_audit_has_no_secret_and_no_codes(
        self, client: AsyncClient, db_session: AsyncSession, app_settings: Settings
    ) -> None:
        await _seed(db_session)
        await db_session.commit()
        _secret, codes = await _enroll(client)

        rows = await db_session.execute(
            select(AuditEvent.id).where(AuditEvent.action == "local_totp_enrolled")
        )
        ids = list(rows.scalars())
        assert len(ids) == 1
        rec = await AuditService(db_session, app_settings).read(ids[0])
        assert rec is not None
        assert rec.payload == {"recovery_codes_issued": 10}
        serialized = str(rec.payload)
        for code in codes:
            assert code not in serialized

    async def test_login_audit_records_which_factor_was_used(
        self, client: AsyncClient, db_session: AsyncSession, app_settings: Settings
    ) -> None:
        await _seed(db_session)
        await db_session.commit()
        _secret, codes = await _enroll(client)
        await client.post(
            "/auth/login/local/totp",
            json={"challenge": await _challenge(client), "code": codes[0]},
        )

        rows = await db_session.execute(
            select(AuditEvent.id).where(AuditEvent.action == "local_login").order_by(AuditEvent.id)
        )
        ids = list(rows.scalars())
        assert len(ids) == 2  # the enrolment sign-in, then the recovery-code one
        svc = AuditService(db_session, app_settings)
        first = await svc.read(ids[0])
        second = await svc.read(ids[1])
        assert first is not None and first.payload["second_factor"] == "totp"
        assert second is not None and second.payload["second_factor"] == "recovery_code"
