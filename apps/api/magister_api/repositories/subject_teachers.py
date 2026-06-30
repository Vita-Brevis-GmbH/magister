"""SubjectTeacherRole (Fachlehrer) repository.

Scope is enforced one level up via the class lookup (ClassRepository); this
repo trusts the caller already verified the class is in scope.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from magister_api.models.base import utcnow
from magister_api.models.subject_teacher_role import SubjectTeacherRole


def _active_window_predicate(now: datetime):
    return and_(
        SubjectTeacherRole.valid_from <= now,
        or_(SubjectTeacherRole.valid_to.is_(None), SubjectTeacherRole.valid_to > now),
    )


class SubjectTeacherRoleRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_for_class(self, class_id: int) -> list[SubjectTeacherRole]:
        stmt = (
            select(SubjectTeacherRole)
            .where(SubjectTeacherRole.class_id == class_id)
            .order_by(SubjectTeacherRole.valid_from, SubjectTeacherRole.id)
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def list_active_for_class(
        self, class_id: int, *, now: datetime | None = None
    ) -> list[SubjectTeacherRole]:
        ts = now or utcnow()
        stmt = (
            select(SubjectTeacherRole)
            .where(SubjectTeacherRole.class_id == class_id)
            .where(_active_window_predicate(ts))
            .order_by(SubjectTeacherRole.subject, SubjectTeacherRole.id)
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def is_active_subject_teacher_of(
        self, *, ad_object_guid: str, class_id: int, now: datetime | None = None
    ) -> bool:
        ts = now or utcnow()
        stmt = (
            select(SubjectTeacherRole.id)
            .where(SubjectTeacherRole.class_id == class_id)
            .where(SubjectTeacherRole.ad_object_guid == ad_object_guid)
            .where(_active_window_predicate(ts))
            .limit(1)
        )
        return (await self.session.execute(stmt)).scalar_one_or_none() is not None

    async def active_class_ids_for_teacher(
        self, ad_object_guid: str, *, now: datetime | None = None
    ) -> list[int]:
        """Class ids where the teacher is an active Fachlehrer."""
        ts = now or utcnow()
        stmt = (
            select(SubjectTeacherRole.class_id)
            .where(SubjectTeacherRole.ad_object_guid == ad_object_guid)
            .where(_active_window_predicate(ts))
            .distinct()
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def get(self, role_id: int) -> SubjectTeacherRole | None:
        return await self.session.get(SubjectTeacherRole, role_id)

    async def add(
        self,
        *,
        class_id: int,
        ad_object_guid: str,
        subject: str,
        valid_from: datetime,
        valid_to: datetime | None,
        created_by: str | None,
    ) -> SubjectTeacherRole:
        row = SubjectTeacherRole(
            class_id=class_id,
            ad_object_guid=ad_object_guid,
            subject=subject,
            valid_from=valid_from,
            valid_to=valid_to,
            created_by=created_by,
        )
        self.session.add(row)
        await self.session.flush()
        return row

    async def end_now(self, row: SubjectTeacherRole) -> SubjectTeacherRole:
        now = utcnow()
        if row.valid_to is None or row.valid_to > now:
            row.valid_to = now
            await self.session.flush()
        return row


__all__ = ["SubjectTeacherRoleRepository"]
