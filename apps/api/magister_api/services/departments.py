"""DepartmentService: orchestrates DepartmentRepository + AuditService."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from magister_api.audit.service import AuditService
from magister_api.config import Settings
from magister_api.models.department import Department
from magister_api.repositories.base import ScopeContext
from magister_api.repositories.departments import DepartmentRepository


class DepartmentNotFoundError(LookupError):
    pass


class DepartmentPermissionError(PermissionError):
    """Raised on cross-school write attempts (unit A → unit B)."""


class DepartmentService:
    def __init__(self, session: AsyncSession, settings: Settings, scope: ScopeContext) -> None:
        self.session = session
        self.settings = settings
        self.scope = scope
        self.repo = DepartmentRepository(session, scope)
        self.audit = AuditService(session, settings)

    async def list_active(self) -> list[Department]:
        return await self.repo.list_active()

    async def get(self, department_id: int) -> Department:
        row = await self.repo.get(department_id)
        if row is None:
            raise DepartmentNotFoundError(str(department_id))
        return row

    async def create(
        self,
        *,
        school_id: int | None,
        name: str,
        kuerzel: str | None,
        details: str | None = None,
        ad_groups: list[str] | None = None,
        ip: str | None,
        request_id: str,
    ) -> Department:
        try:
            row = await self.repo.create(
                school_id=school_id,
                name=name,
                kuerzel=kuerzel,
                details=details,
                ad_groups=ad_groups,
            )
        except PermissionError as exc:
            raise DepartmentPermissionError(str(exc) or "school_out_of_scope") from exc
        await self.audit.emit(
            action="department_created",
            target_kind="department",
            target_id=str(row.id),
            actor_upn=self.scope.upn,
            actor_object_guid=self.scope.ad_object_guid,
            school_id=row.school_id,
            ip=ip,
            request_id=request_id,
            payload={"name": row.name, "kuerzel": row.kuerzel},
        )
        return row

    async def update(
        self,
        *,
        department_id: int,
        name: str | None,
        kuerzel: str | None,
        details: str | None,
        ad_groups: list[str] | None = None,
        ip: str | None,
        request_id: str,
    ) -> Department:
        row = await self.get(department_id)
        old_name, old_kuerzel = row.name, row.kuerzel
        old_details = row.details
        changed = await self.repo.update(
            row, name=name, kuerzel=kuerzel, details=details, ad_groups=ad_groups
        )
        if changed:
            await self.audit.emit(
                action="department_updated",
                target_kind="department",
                target_id=str(row.id),
                actor_upn=self.scope.upn,
                actor_object_guid=self.scope.ad_object_guid,
                school_id=row.school_id,
                ip=ip,
                request_id=request_id,
                payload={
                    "old_name": old_name,
                    "new_name": row.name,
                    "old_kuerzel": old_kuerzel,
                    "new_kuerzel": row.kuerzel,
                    "details_changed": old_details != row.details,
                },
            )
        return row

    async def archive(
        self,
        *,
        department_id: int,
        ip: str | None,
        request_id: str,
    ) -> Department:
        row = await self.get(department_id)
        row = await self.repo.archive(row)
        await self.audit.emit(
            action="department_archived",
            target_kind="department",
            target_id=str(row.id),
            actor_upn=self.scope.upn,
            actor_object_guid=self.scope.ad_object_guid,
            school_id=row.school_id,
            ip=ip,
            request_id=request_id,
            payload={"name": row.name},
        )
        return row
