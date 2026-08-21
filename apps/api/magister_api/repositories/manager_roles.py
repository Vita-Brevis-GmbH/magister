"""ManagerRole repository.

Scope is enforced one level up via the department lookup (DepartmentRepository),
so this repo trusts that the caller already verified the department is in scope.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from magister_api.models.base import utcnow
from magister_api.models.manager_role import ManagerRole


def _active_window(now: datetime):
    return and_(
        ManagerRole.valid_from <= now,
        or_(ManagerRole.valid_to.is_(None), ManagerRole.valid_to > now),
    )


class ManagerRoleRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_active(
        self, department_id: int, *, now: datetime | None = None
    ) -> list[ManagerRole]:
        ts = now or utcnow()
        stmt = (
            select(ManagerRole)
            .where(ManagerRole.department_id == department_id)
            .where(_active_window(ts))
            .order_by(ManagerRole.role, ManagerRole.id)
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def get(self, role_id: int) -> ManagerRole | None:
        return await self.session.get(ManagerRole, role_id)

    async def add(
        self,
        *,
        department_id: int,
        ad_object_guid: str,
        role: str,
        valid_from: datetime,
        valid_to: datetime | None,
        created_by: str | None,
    ) -> ManagerRole:
        row = ManagerRole(
            department_id=department_id,
            ad_object_guid=ad_object_guid,
            role=role,
            valid_from=valid_from,
            valid_to=valid_to,
            created_by=created_by,
        )
        self.session.add(row)
        await self.session.flush()
        return row

    async def end_now(self, row: ManagerRole) -> ManagerRole:
        now = utcnow()
        if row.valid_to is None or row.valid_to > now:
            row.valid_to = now
            await self.session.flush()
        return row
