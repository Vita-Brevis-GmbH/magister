"""DepartmentMembership repository.

Scope is enforced one level up via the department lookup (DepartmentRepository),
so this repo trusts that the caller already verified the department is in scope.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from magister_api.models.base import utcnow
from magister_api.models.department_membership import DepartmentMembership


def _active_window(now: datetime):
    return and_(
        DepartmentMembership.valid_from <= now,
        or_(DepartmentMembership.valid_to.is_(None), DepartmentMembership.valid_to > now),
    )


class DepartmentMembershipRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_active(
        self, department_id: int, *, now: datetime | None = None
    ) -> list[DepartmentMembership]:
        ts = now or utcnow()
        stmt = (
            select(DepartmentMembership)
            .where(DepartmentMembership.department_id == department_id)
            .where(_active_window(ts))
            .order_by(DepartmentMembership.valid_from, DepartmentMembership.id)
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def list_active_for_person(
        self, ad_object_guid: str, *, now: datetime | None = None
    ) -> list[DepartmentMembership]:
        """Active memberships of a person across ALL departments (unscoped).

        The caller (offboarding) re-checks each row's department against the
        actor's school scope, so this crosses scope by design.
        """
        ts = now or utcnow()
        stmt = (
            select(DepartmentMembership)
            .where(DepartmentMembership.ad_object_guid == ad_object_guid)
            .where(_active_window(ts))
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def get(self, membership_id: int) -> DepartmentMembership | None:
        return await self.session.get(DepartmentMembership, membership_id)

    async def add(
        self,
        *,
        department_id: int,
        ad_object_guid: str,
        valid_from: datetime,
        valid_to: datetime | None,
        created_by: str | None,
    ) -> DepartmentMembership:
        row = DepartmentMembership(
            department_id=department_id,
            ad_object_guid=ad_object_guid,
            valid_from=valid_from,
            valid_to=valid_to,
            created_by=created_by,
        )
        self.session.add(row)
        await self.session.flush()
        return row

    async def end_now(self, row: DepartmentMembership) -> DepartmentMembership:
        now = utcnow()
        if row.valid_to is None or row.valid_to > now:
            row.valid_to = now
            await self.session.flush()
        return row
