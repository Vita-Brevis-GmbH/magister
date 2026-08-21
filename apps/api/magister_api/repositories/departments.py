"""Department repository — all reads/writes are school-scope filtered."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from magister_api.models.department import (
    DEPARTMENT_STATUS_ACTIVE,
    DEPARTMENT_STATUS_ARCHIVED,
    Department,
)
from magister_api.repositories.base import BaseRepository, ScopeContext


class DepartmentRepository(BaseRepository):
    def __init__(self, session: AsyncSession, scope: ScopeContext) -> None:
        super().__init__(session, scope)

    async def list_active(self) -> list[Department]:
        stmt = self.apply_scope(
            select(Department).where(Department.status == DEPARTMENT_STATUS_ACTIVE),
            Department.school_id,
        ).order_by(Department.school_id, Department.name)
        return list((await self.session.execute(stmt)).scalars().all())

    async def get(self, department_id: int) -> Department | None:
        stmt = self.apply_scope(
            select(Department).where(Department.id == department_id),
            Department.school_id,
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def create(
        self,
        *,
        school_id: int,
        name: str,
        kuerzel: str | None,
        details: str | None = None,
    ) -> Department:
        if not self.scope.can_access_school(school_id):
            raise PermissionError("school_out_of_scope")
        row = Department(
            school_id=school_id,
            name=name,
            kuerzel=kuerzel,
            details=details,
            status=DEPARTMENT_STATUS_ACTIVE,
        )
        self.session.add(row)
        await self.session.flush()
        return row

    async def update(
        self,
        dep: Department,
        *,
        name: str | None = None,
        kuerzel: str | None = None,
        details: str | None = None,
    ) -> bool:
        """Apply provided fields; returns whether anything changed."""
        changed = False
        if name is not None and name != dep.name:
            dep.name = name
            changed = True
        if kuerzel is not None and kuerzel != dep.kuerzel:
            dep.kuerzel = kuerzel
            changed = True
        if details is not None and details != dep.details:
            dep.details = details
            changed = True
        if changed:
            await self.session.flush()
        return changed

    async def archive(self, dep: Department) -> Department:
        dep.status = DEPARTMENT_STATUS_ARCHIVED
        await self.session.flush()
        return dep
