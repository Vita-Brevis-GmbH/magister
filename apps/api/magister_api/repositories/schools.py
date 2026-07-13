"""School repository.

Listing is scoped to the caller's school access (schools are the scope entity
themselves, so the filter runs against ``School.id``). Create/update/delete are
admin-only operations gated at the router, so they run unscoped here.
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from magister_api.models.auth import AdUserCache, RoleAssignment
from magister_api.models.import_job import ImportJob
from magister_api.models.school import School
from magister_api.models.school_class import SchoolClass
from magister_api.repositories.base import BaseRepository, ScopeContext


class SchoolRepository(BaseRepository):
    def __init__(self, session: AsyncSession, scope: ScopeContext) -> None:
        super().__init__(session, scope)

    async def list_in_scope(self) -> list[School]:
        stmt = self.apply_scope(select(School), School.id).order_by(School.name)
        return list((await self.session.execute(stmt)).scalars().all())

    async def get_in_scope(self, school_id: int) -> School | None:
        stmt = self.apply_scope(select(School).where(School.id == school_id), School.id)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def get(self, school_id: int) -> School | None:
        # scope-bypass: admin-only management path (router gate require_admin).
        return await self.session.get(School, school_id)

    async def create(self, **fields: object) -> School:
        row = School(**fields)
        self.session.add(row)
        await self.session.flush()
        return row

    async def update(self, school: School, changes: dict[str, object]) -> School:
        for key, value in changes.items():
            setattr(school, key, value)
        await self.session.flush()
        return school

    async def delete(self, school: School) -> None:
        await self.session.delete(school)
        await self.session.flush()

    async def count_dependents(self, school_id: int) -> int:
        # scope-bypass: admin-only delete guard; refuse deleting a school that
        # still owns domain data (classes, users, role grants or import jobs).
        # Audit events are intentionally excluded — their FK is SET NULL.
        total = 0
        for model, column in (
            (SchoolClass, SchoolClass.school_id),
            (AdUserCache, AdUserCache.school_id),
            (RoleAssignment, RoleAssignment.school_id),
            (ImportJob, ImportJob.school_id),
        ):
            stmt = select(func.count()).select_from(model).where(column == school_id)
            total += int((await self.session.execute(stmt)).scalar_one())
        return total


__all__ = ["SchoolRepository"]
