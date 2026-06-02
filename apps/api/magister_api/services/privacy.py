"""Privacy / Subject-Access export (revDSG Art. 25, M3 US-4 + US-5).

Aggregates everything Magister knows about a single user:

- AD cache row (identity attributes)
- Class memberships (active + historical)
- Class-teacher roles (active + historical)
- Audit events where the user was either ``target`` or ``actor``

Reads encrypted audit payloads via pgcrypto (per CLAUDE.md "Immer"-Regel).

The export itself is audited (``subject_access_export``) so we can prove who
fetched whose data, when.
"""

from __future__ import annotations

import csv
import io
import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from magister_api.audit.service import AuditService
from magister_api.config import Settings
from magister_api.models.audit import AuditEvent
from magister_api.models.auth import AdUserCache
from magister_api.models.class_membership import ClassMembership
from magister_api.models.class_teacher_role import ClassTeacherRole
from magister_api.models.school import School
from magister_api.models.school_class import SchoolClass
from magister_api.repositories.base import ScopeContext


class SubjectNotFoundError(LookupError):
    pass


class SubjectNotInScopeError(LookupError):
    pass


@dataclass(frozen=True)
class SubjectAccessReport:
    user: dict[str, Any]
    school: dict[str, Any] | None
    memberships: list[dict[str, Any]]
    teacher_roles: list[dict[str, Any]]
    audit_events: list[dict[str, Any]]


class PrivacyService:
    def __init__(self, session: AsyncSession, settings: Settings, scope: ScopeContext) -> None:
        self.session = session
        self.settings = settings
        self.scope = scope
        self.audit = AuditService(session, settings)

    async def subject_access(
        self,
        *,
        target_guid: str,
        ip: str | None,
        request_id: str,
    ) -> SubjectAccessReport:
        user = await self.session.get(AdUserCache, target_guid)
        if user is None:
            raise SubjectNotFoundError(target_guid)

        # Scope check.
        if not self.scope.is_admin and (
            user.school_id is None or user.school_id not in self.scope.school_scope
        ):
            raise SubjectNotInScopeError(target_guid)

        school = await self.session.get(School, user.school_id) if user.school_id else None

        memberships = await self._memberships(user.ad_object_guid)
        teacher_roles = await self._teacher_roles(user.ad_object_guid)
        audit_events = await self._audit_events(user.ad_object_guid)

        # Self-audit the export.
        await self.audit.emit(
            action="subject_access_export",
            target_kind="user",
            target_id=user.ad_object_guid,
            actor_upn=self.scope.upn,
            actor_object_guid=self.scope.ad_object_guid,
            school_id=user.school_id,
            ip=ip,
            request_id=request_id,
            payload={"target_upn": user.upn, "audit_event_count": len(audit_events)},
        )

        return SubjectAccessReport(
            user=_user_dict(user),
            school={"id": school.id, "name": school.name} if school else None,
            memberships=memberships,
            teacher_roles=teacher_roles,
            audit_events=audit_events,
        )

    async def _memberships(self, guid: str) -> list[dict[str, Any]]:
        stmt = (
            select(
                ClassMembership.id,
                ClassMembership.class_id,
                SchoolClass.name,
                SchoolClass.school_id,
                ClassMembership.valid_from,
                ClassMembership.valid_to,
                ClassMembership.created_at,
                ClassMembership.created_by,
            )
            .join(SchoolClass, SchoolClass.id == ClassMembership.class_id)
            .where(ClassMembership.ad_object_guid == guid)
            .order_by(ClassMembership.valid_from.desc())
        )
        rows = (await self.session.execute(stmt)).all()
        return [
            {
                "id": r[0],
                "class_id": r[1],
                "class_name": r[2],
                "school_id": r[3],
                "valid_from": r[4].isoformat(),
                "valid_to": r[5].isoformat() if r[5] else None,
                "created_at": r[6].isoformat(),
                "created_by": r[7],
            }
            for r in rows
        ]

    async def _teacher_roles(self, guid: str) -> list[dict[str, Any]]:
        stmt = (
            select(
                ClassTeacherRole.id,
                ClassTeacherRole.class_id,
                SchoolClass.name,
                SchoolClass.school_id,
                ClassTeacherRole.role,
                ClassTeacherRole.valid_from,
                ClassTeacherRole.valid_to,
                ClassTeacherRole.created_at,
                ClassTeacherRole.created_by,
            )
            .join(SchoolClass, SchoolClass.id == ClassTeacherRole.class_id)
            .where(ClassTeacherRole.ad_object_guid == guid)
            .order_by(ClassTeacherRole.valid_from.desc())
        )
        rows = (await self.session.execute(stmt)).all()
        return [
            {
                "id": r[0],
                "class_id": r[1],
                "class_name": r[2],
                "school_id": r[3],
                "role": r[4],
                "valid_from": r[5].isoformat(),
                "valid_to": r[6].isoformat() if r[6] else None,
                "created_at": r[7].isoformat(),
                "created_by": r[8],
            }
            for r in rows
        ]

    async def _audit_events(self, guid: str) -> list[dict[str, Any]]:
        """All audit events where the user is target OR actor — decrypted."""
        key = self.settings.audit_key.get_secret_value()
        stmt = (
            select(
                AuditEvent.id,
                AuditEvent.ts,
                AuditEvent.action,
                AuditEvent.target_kind,
                AuditEvent.target_id,
                AuditEvent.actor_upn,
                AuditEvent.actor_object_guid,
                AuditEvent.school_id,
                AuditEvent.ip,
                AuditEvent.request_id,
                func.pgp_sym_decrypt(AuditEvent.payload, key).label("payload_text"),
            )
            .where(
                or_(
                    (AuditEvent.target_kind == "user") & (AuditEvent.target_id == guid),
                    AuditEvent.actor_object_guid == guid,
                )
            )
            .order_by(AuditEvent.ts.desc())
        )
        rows = (await self.session.execute(stmt)).all()
        out: list[dict[str, Any]] = []
        for r in rows:
            try:
                payload = json.loads(r.payload_text) if r.payload_text else {}
            except (TypeError, json.JSONDecodeError):
                payload = {}
            out.append(
                {
                    "id": r.id,
                    "ts": r.ts.isoformat(),
                    "action": r.action,
                    "target_kind": r.target_kind,
                    "target_id": r.target_id,
                    "actor_upn": r.actor_upn,
                    "actor_object_guid": r.actor_object_guid,
                    "school_id": r.school_id,
                    "ip": r.ip,
                    "request_id": r.request_id,
                    "payload": payload,
                    "role": ("actor" if r.actor_object_guid == guid else "target"),
                }
            )
        return out


def _user_dict(u: AdUserCache) -> dict[str, Any]:
    return {
        "ad_object_guid": u.ad_object_guid,
        "school_id": u.school_id,
        "upn": u.upn,
        "sam_account_name": u.sam_account_name,
        "display_name": u.display_name,
        "given_name": u.given_name,
        "surname": u.surname,
        "mail": u.mail,
        "kind": u.kind,
        "enabled": u.enabled,
        "last_sync_at": u.last_sync_at.isoformat() if u.last_sync_at else None,
        "street_address": u.street_address,
        "locality": u.locality,
        "postal_code": u.postal_code,
        "country": u.country,
        "device_name": u.device_name,
        "temp_device_name": u.temp_device_name,
        "ms_ds_consistency_guid": u.ms_ds_consistency_guid,
    }


def render_csv(report: SubjectAccessReport) -> str:
    """Flatten the subject-access report into a single CSV for offline handout.

    The CSV has section headers (``# === Identity ===`` etc.) so it stays
    human-readable when opened in Excel/LibreOffice.
    """
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")

    writer.writerow(["# === Identity ==="])
    writer.writerow(["field", "value"])
    for k, v in report.user.items():
        writer.writerow([k, _stringify(v)])
    writer.writerow([])

    if report.school:
        writer.writerow(["# === School ==="])
        writer.writerow(["field", "value"])
        for k, v in report.school.items():
            writer.writerow([k, _stringify(v)])
        writer.writerow([])

    writer.writerow(["# === Class memberships (students) ==="])
    if report.memberships:
        keys = list(report.memberships[0].keys())
        writer.writerow(keys)
        for m in report.memberships:
            writer.writerow([_stringify(m[k]) for k in keys])
    else:
        writer.writerow(["(none)"])
    writer.writerow([])

    writer.writerow(["# === Class-teacher roles ==="])
    if report.teacher_roles:
        keys = list(report.teacher_roles[0].keys())
        writer.writerow(keys)
        for tr in report.teacher_roles:
            writer.writerow([_stringify(tr[k]) for k in keys])
    else:
        writer.writerow(["(none)"])
    writer.writerow([])

    writer.writerow(["# === Audit events ==="])
    if report.audit_events:
        keys = [
            "ts",
            "role",
            "action",
            "target_kind",
            "target_id",
            "actor_upn",
            "school_id",
            "ip",
            "payload",
        ]
        writer.writerow(keys)
        for ev in report.audit_events:
            writer.writerow(
                [
                    ev["ts"],
                    ev["role"],
                    ev["action"],
                    ev["target_kind"],
                    ev["target_id"],
                    ev["actor_upn"],
                    ev["school_id"],
                    ev["ip"],
                    json.dumps(ev["payload"], ensure_ascii=False, sort_keys=True),
                ]
            )
    else:
        writer.writerow(["(none)"])

    return buf.getvalue()


def _stringify(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, datetime):
        return v.isoformat()
    return str(v)


__all__ = [
    "PrivacyService",
    "SubjectAccessReport",
    "SubjectNotFoundError",
    "SubjectNotInScopeError",
    "render_csv",
]
