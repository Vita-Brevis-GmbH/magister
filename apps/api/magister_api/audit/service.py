"""Audit service: emit + read with pgcrypto column-level encryption."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import func, insert, select
from sqlalchemy.ext.asyncio import AsyncSession

from magister_api.audit.allowlist import validate_audit_payload
from magister_api.config import Settings
from magister_api.models.audit import AuditEvent


@dataclass(frozen=True)
class AuditEventRecord:
    id: int
    ts: datetime
    actor_upn: str | None
    actor_object_guid: str | None
    action: str
    target_kind: str
    target_id: str
    school_id: int | None
    ip: str | None
    request_id: str
    payload: dict[str, Any]


class AuditService:
    """Single entry point for writing and reading audit events.

    Per CLAUDE.md "Immer"-Regel: read encrypted payloads only via this service,
    never via raw ``SELECT payload``.
    """

    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self.session = session
        self._settings = settings

    @property
    def _key(self) -> str:
        key = self._settings.audit_key.get_secret_value()
        if not key:
            raise RuntimeError("MAGISTER_AUDIT_KEY is empty — audit emit refused")
        return key

    async def emit(
        self,
        *,
        action: str,
        target_kind: str,
        target_id: str,
        actor_upn: str | None,
        actor_object_guid: str | None,
        school_id: int | None,
        ip: str | None,
        request_id: str,
        payload: dict[str, Any],
    ) -> int:
        """Validate, JSON-encode, encrypt and persist an audit event.

        Returns the new ``audit_events.id``.
        """
        validate_audit_payload(payload)
        plaintext = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)

        stmt = (
            insert(AuditEvent)
            .values(
                actor_upn=actor_upn,
                actor_object_guid=actor_object_guid,
                action=action,
                target_kind=target_kind,
                target_id=target_id,
                school_id=school_id,
                ip=ip,
                request_id=request_id,
                payload=func.pgp_sym_encrypt(plaintext, self._key),
            )
            .returning(AuditEvent.id)
        )
        result = await self.session.execute(stmt)
        new_id = result.scalar_one()
        return int(new_id)

    async def read(self, event_id: int) -> AuditEventRecord | None:
        """Decrypt and return a single audit event by id."""
        stmt = select(
            AuditEvent.id,
            AuditEvent.ts,
            AuditEvent.actor_upn,
            AuditEvent.actor_object_guid,
            AuditEvent.action,
            AuditEvent.target_kind,
            AuditEvent.target_id,
            AuditEvent.school_id,
            AuditEvent.ip,
            AuditEvent.request_id,
            func.pgp_sym_decrypt(AuditEvent.payload, self._key).label("payload_text"),
        ).where(AuditEvent.id == event_id)
        result = await self.session.execute(stmt)
        row = result.one_or_none()
        if row is None:
            return None
        return AuditEventRecord(
            id=row.id,
            ts=row.ts,
            actor_upn=row.actor_upn,
            actor_object_guid=row.actor_object_guid,
            action=row.action,
            target_kind=row.target_kind,
            target_id=row.target_id,
            school_id=row.school_id,
            ip=row.ip,
            request_id=row.request_id,
            payload=json.loads(row.payload_text),
        )
