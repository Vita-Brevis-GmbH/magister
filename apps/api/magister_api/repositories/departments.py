"""Department repository — school-scope filtered (global departments included).

A department may be bound to a Standort (``school_id``) or be *global*
(``school_id IS NULL``, standortübergreifend). Global departments are visible to
every manager; scoped departments only within the caller's org-unit scope.
Creating a global department requires Admin (it sits outside any single scope).
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import Select

from magister_api.models.department import (
    DEPARTMENT_STATUS_ACTIVE,
    DEPARTMENT_STATUS_ARCHIVED,
    Department,
)
from magister_api.repositories.base import BaseRepository, ScopeContext


class DepartmentRepository(BaseRepository):
    def __init__(self, session: AsyncSession, scope: ScopeContext) -> None:
        super().__init__(session, scope)

    def _scoped(self, stmt: Select[Any]) -> Select[Any]:
        """Filter to departments the caller may see: global (NULL) + in-scope."""
        if self.scope.is_admin:
            return stmt
        conds = [Department.school_id.is_(None)]
        if self.scope.school_scope:
            conds.append(Department.school_id.in_(self.scope.school_scope))
        return stmt.where(or_(*conds))

    async def list_active(self) -> list[Department]:
        stmt = self._scoped(
            select(Department).where(Department.status == DEPARTMENT_STATUS_ACTIVE)
        ).order_by(Department.school_id.nulls_first(), Department.name)
        return list((await self.session.execute(stmt)).scalars().all())

    async def get(self, department_id: int) -> Department | None:
        stmt = self._scoped(select(Department).where(Department.id == department_id))
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def create(
        self,
        *,
        school_id: int | None,
        name: str,
        kuerzel: str | None,
        details: str | None = None,
        ad_groups: list[str] | None = None,
    ) -> Department:
        if school_id is None:
            # A global (unbound) department is not inside any single scope.
            if not self.scope.is_admin:
                raise PermissionError("global_department_requires_admin")
        elif not self.scope.can_access_school(school_id):
            raise PermissionError("school_out_of_scope")
        row = Department(
            school_id=school_id,
            name=name,
            kuerzel=kuerzel,
            details=details,
            ad_groups=list(ad_groups or []),
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
        ad_groups: list[str] | None = None,
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
        if ad_groups is not None and list(ad_groups) != list(dep.ad_groups or []):
            dep.ad_groups = list(ad_groups)
            changed = True
        if changed:
            await self.session.flush()
        return changed

    async def archive(self, dep: Department) -> Department:
        dep.status = DEPARTMENT_STATUS_ARCHIVED
        await self.session.flush()
        return dep
