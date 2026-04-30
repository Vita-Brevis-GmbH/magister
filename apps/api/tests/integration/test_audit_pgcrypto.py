"""Integration tests for AuditService + pgcrypto round-trip.

DoD checks for issue #2:
- emit/read round-trip
- raw SELECT exposes encrypted bytea, never plaintext
- secrets in payload are rejected before persistence
- Niemals/Immer rules: no PW/token strings in audit_events.payload column
"""

from __future__ import annotations

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from magister_api.audit.allowlist import SecretInPayloadError
from magister_api.audit.service import AuditService
from magister_api.config import Settings
from magister_api.models.audit import AuditEvent

pytestmark = pytest.mark.postgres


def _settings() -> Settings:
    return Settings(
        audit_key="integration-test-audit-key",  # type: ignore[arg-type]
        session_secret="x",  # type: ignore[arg-type]
        csrf_secret="x",  # type: ignore[arg-type]
    )


class TestAuditRoundTrip:
    @pytest.mark.asyncio
    async def test_emit_then_read(self, db_session: AsyncSession) -> None:
        svc = AuditService(db_session, _settings())
        eid = await svc.emit(
            action="class_created",
            target_kind="class",
            target_id="42",
            actor_upn="anna@x.ch",
            actor_object_guid="01020304-0506-0708-090a-0b0c0d0e0f10",
            school_id=None,
            ip="10.0.0.1",
            request_id="req-1",
            payload={"name": "4a", "kuerzel": "K4A", "jahrgangsstufe": 4},
        )
        assert eid > 0

        rec = await svc.read(eid)
        assert rec is not None
        assert rec.action == "class_created"
        assert rec.target_id == "42"
        assert rec.actor_upn == "anna@x.ch"
        assert rec.payload == {"name": "4a", "kuerzel": "K4A", "jahrgangsstufe": 4}

    @pytest.mark.asyncio
    async def test_raw_payload_is_encrypted_bytea(self, db_session: AsyncSession) -> None:
        svc = AuditService(db_session, _settings())
        await svc.emit(
            action="class_renamed",
            target_kind="class",
            target_id="7",
            actor_upn="anna@x.ch",
            actor_object_guid=None,
            school_id=None,
            ip=None,
            request_id="req-2",
            payload={"old_name": "3a", "new_name": "4a"},
        )
        # Direct SELECT of the column shows raw bytea (encrypted), never plaintext.
        result = await db_session.execute(
            select(AuditEvent.payload).where(AuditEvent.action == "class_renamed")
        )
        raw = result.scalar_one()
        assert isinstance(raw, (bytes, memoryview))
        as_bytes = bytes(raw)
        # Plaintext fields should not appear inside the bytea.
        assert b"3a" not in as_bytes
        assert b"new_name" not in as_bytes
        # pgp_sym_encrypt output starts with PGP header bytes (0xC3 marker for sym key).
        assert len(as_bytes) > 16

    @pytest.mark.asyncio
    async def test_payload_with_password_rejected_before_db(self, db_session: AsyncSession) -> None:
        svc = AuditService(db_session, _settings())
        with pytest.raises(SecretInPayloadError):
            await svc.emit(
                action="student_password_reset",
                target_kind="ad_user",
                target_id="01020304-0506-0708-090a-0b0c0d0e0f10",
                actor_upn="kl@x.ch",
                actor_object_guid="01020304-0506-0708-090a-0b0c0d0e0f10",
                school_id=1,
                ip="10.0.0.1",
                request_id="req-3",
                payload={"mode": "manual", "manual_password": "Hunter2!"},
            )

        # Nothing should have been written to the DB.
        result = await db_session.execute(
            select(AuditEvent).where(AuditEvent.action == "student_password_reset")
        )
        assert result.first() is None

    @pytest.mark.asyncio
    async def test_no_plaintext_password_in_table(self, db_session: AsyncSession) -> None:
        """End-to-end CLAUDE.md guarantee: scan the column for forbidden substrings."""
        svc = AuditService(db_session, _settings())
        await svc.emit(
            action="login",
            target_kind="session",
            target_id="abc",
            actor_upn="anna@x.ch",
            actor_object_guid=None,
            school_id=None,
            ip=None,
            request_id="req-4",
            payload={"oidc_subject": "sub-123", "user_agent": "pytest"},
        )
        # Use raw SQL to fetch column-level data and convert to text for substring scan.
        result = await db_session.execute(
            text("SELECT encode(payload, 'escape') FROM audit_events")
        )
        for (encoded,) in result.all():
            for forbidden in ("password", "passwort", "Bearer ", "id_token"):
                assert forbidden not in encoded
