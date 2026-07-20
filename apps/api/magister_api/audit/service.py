"""Audit service: emit + read with pgcrypto column-level encryption."""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy import ColumnElement, delete, func, insert, select
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
                key_id=self._settings.audit_key_id,
            )
            .returning(AuditEvent.id)
        )
        result = await self.session.execute(stmt)
        new_id = result.scalar_one()
        return int(new_id)

    async def purge(
        self,
        *,
        actor_upn: str | None,
        actor_object_guid: str | None,
        ip: str | None,
        request_id: str,
    ) -> int:
        """Delete the whole activity history, then record the reset itself.

        Used before hand-over/delivery so the customer starts with a clean
        activity overview. The reset is itself audited (Niemals-Regel: keine
        schreibende Operation ohne Audit-Event), so the fresh log carries a
        single ``audit_reset`` entry documenting who cleared it and how many
        rows were removed. Returns the number of events deleted.
        """
        count = int(
            (await self.session.execute(select(func.count()).select_from(AuditEvent))).scalar_one()
        )
        await self.session.execute(delete(AuditEvent))
        await self.emit(
            action="audit_reset",
            target_kind="audit",
            target_id="all",
            actor_upn=actor_upn,
            actor_object_guid=actor_object_guid,
            school_id=None,
            ip=ip,
            request_id=request_id,
            payload={"deleted": count},
        )
        return count

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

    async def list(
        self,
        *,
        filter: AuditFilter,
        offset: int = 0,
        limit: int = 50,
    ) -> AuditListing:
        """Filtered, paginated, decrypted listing for the audit-UI.

        ``filter.school_ids`` semantics:
        - ``None``  → no school filter (admin view: includes ``school_id=NULL``)
        - ``[]``    → caller has empty school scope ⇒ always-empty result
        - ``[..]``  → restrict to ``school_id IN ids`` (excludes NULLs)
        """
        where: list[ColumnElement[bool]] = []
        if filter.action is not None:
            where.append(AuditEvent.action == filter.action)
        if filter.target_kind is not None:
            where.append(AuditEvent.target_kind == filter.target_kind)
        if filter.target_id is not None:
            where.append(AuditEvent.target_id == filter.target_id)
        if filter.actor_upn is not None:
            where.append(func.lower(AuditEvent.actor_upn).contains(filter.actor_upn.lower()))
        if filter.from_ts is not None:
            where.append(AuditEvent.ts >= filter.from_ts)
        if filter.to_ts is not None:
            where.append(AuditEvent.ts <= filter.to_ts)
        if filter.school_ids is not None:
            if not filter.school_ids:
                return AuditListing(items=[], total=0)
            where.append(AuditEvent.school_id.in_(filter.school_ids))

        count_stmt = select(func.count()).select_from(AuditEvent).where(*where)
        total = int((await self.session.execute(count_stmt)).scalar_one())

        stmt = (
            select(
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
            )
            .where(*where)
            .order_by(AuditEvent.ts.desc(), AuditEvent.id.desc())
            .offset(offset)
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        items = [
            AuditEventRecord(
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
            for row in result.all()
        ]
        return AuditListing(items=items, total=total)


@dataclass(frozen=True)
class AuditFilter:
    action: str | None = None
    target_kind: str | None = None
    target_id: str | None = None
    actor_upn: str | None = None  # substring, case-insensitive
    from_ts: datetime | None = None
    to_ts: datetime | None = None
    # ``None`` = no filter (admin). Empty list = empty scope ⇒ empty result.
    school_ids: Sequence[int] | None = None


@dataclass(frozen=True)
class AuditListing:
    items: list[AuditEventRecord] = field(default_factory=list)
    total: int = 0
