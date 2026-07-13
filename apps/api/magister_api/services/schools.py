"""SchoolService: orchestrates SchoolRepository + AuditService.

Schools are org-level scope entities; create/update/delete are admin-only
(gated at the router) and each mutation emits an audit event.
"""

from __future__ import annotations

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from magister_api.audit.service import AuditService
from magister_api.config import Settings
from magister_api.models.school import School
from magister_api.repositories.base import ScopeContext
from magister_api.repositories.schools import SchoolRepository

# Fields that carry no privacy risk and are safe to name in the audit payload.
_AUDIT_SAFE_FIELDS = frozenset(
    {
        "name",
        "kuerzel",
        "scope_short",
        "street",
        "postal_code",
        "city",
        "phone",
        "latitude",
        "longitude",
    }
)


class SchoolNotFoundError(LookupError):
    pass


class SchoolKuerzelConflictError(ValueError):
    """Kürzel collides with an existing school (unique constraint)."""


class SchoolInUseError(ValueError):
    """Refused delete: the school still owns classes, users, roles or imports."""


class SchoolService:
    def __init__(self, session: AsyncSession, settings: Settings, scope: ScopeContext) -> None:
        self.session = session
        self.settings = settings
        self.scope = scope
        self.repo = SchoolRepository(session, scope)
        self.audit = AuditService(session, settings)

    async def get(self, school_id: int) -> School:
        row = await self.repo.get(school_id)
        if row is None:
            raise SchoolNotFoundError(str(school_id))
        return row

    async def create(self, *, fields: dict[str, object], ip: str | None, request_id: str) -> School:
        try:
            row = await self.repo.create(**fields)
        except IntegrityError as exc:
            raise SchoolKuerzelConflictError("kuerzel") from exc
        await self._emit("school_created", row, ip, request_id, self._safe_payload(fields))
        return row

    async def update(
        self, *, school_id: int, changes: dict[str, object], ip: str | None, request_id: str
    ) -> School:
        row = await self.get(school_id)
        try:
            row = await self.repo.update(row, changes)
        except IntegrityError as exc:
            raise SchoolKuerzelConflictError("kuerzel") from exc
        await self._emit(
            "school_updated", row, ip, request_id, {"changed_keys": sorted(changes.keys())}
        )
        return row

    async def delete(self, *, school_id: int, ip: str | None, request_id: str) -> None:
        row = await self.get(school_id)
        dependents = await self.repo.count_dependents(school_id)
        if dependents > 0:
            raise SchoolInUseError(str(dependents))
        payload = {"name": row.name, "kuerzel": row.kuerzel}
        await self.repo.delete(row)
        # The school no longer exists, so the audit row must not reference it
        # (school_id=None); target_id keeps the deleted school's id for the trail.
        await self.audit.emit(
            action="school_deleted",
            target_kind="school",
            target_id=str(school_id),
            actor_upn=self.scope.upn,
            actor_object_guid=self.scope.ad_object_guid,
            school_id=None,
            ip=ip,
            request_id=request_id,
            payload=payload,
        )

    @staticmethod
    def _safe_payload(fields: dict[str, object]) -> dict[str, object]:
        return {k: v for k, v in fields.items() if k in _AUDIT_SAFE_FIELDS}

    async def _emit(
        self,
        action: str,
        row: School,
        ip: str | None,
        request_id: str,
        payload: dict[str, object],
    ) -> None:
        await self.audit.emit(
            action=action,
            target_kind="school",
            target_id=str(row.id),
            actor_upn=self.scope.upn,
            actor_object_guid=self.scope.ad_object_guid,
            school_id=row.id,
            ip=ip,
            request_id=request_id,
            payload=payload,
        )


__all__ = [
    "SchoolInUseError",
    "SchoolKuerzelConflictError",
    "SchoolNotFoundError",
    "SchoolService",
]
