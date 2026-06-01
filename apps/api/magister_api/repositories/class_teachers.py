"""ClassTeacherRole repository.

Scope is enforced one level up via the class lookup (ClassRepository), so this
repo trusts that the caller already verified the class belongs to the user's scope.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from magister_api.models.base import utcnow
from magister_api.models.class_teacher_role import KL_ROLE_STELLVERTRETUNG, ClassTeacherRole
from magister_api.models.school_class import SchoolClass


@dataclass(frozen=True)
class SubstitutionRow:
    role: ClassTeacherRole
    class_name: str
    school_id: int | None


def _active_window_predicate(now: datetime):
    """Predicate: now is inside [valid_from, valid_to|+infty)."""
    return and_(
        ClassTeacherRole.valid_from <= now,
        or_(
            ClassTeacherRole.valid_to.is_(None),
            ClassTeacherRole.valid_to > now,
        ),
    )


class ClassTeacherRoleRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_for_class(self, class_id: int) -> list[ClassTeacherRole]:
        stmt = (
            select(ClassTeacherRole)
            .where(ClassTeacherRole.class_id == class_id)
            .order_by(ClassTeacherRole.valid_from, ClassTeacherRole.id)
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def list_active_for_class(
        self, class_id: int, *, now: datetime | None = None
    ) -> list[ClassTeacherRole]:
        ts = now or utcnow()
        stmt = (
            select(ClassTeacherRole)
            .where(ClassTeacherRole.class_id == class_id)
            .where(_active_window_predicate(ts))
            .order_by(ClassTeacherRole.role, ClassTeacherRole.id)
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def is_active_kl_of(
        self,
        *,
        ad_object_guid: str,
        class_id: int,
        now: datetime | None = None,
    ) -> bool:
        ts = now or utcnow()
        stmt = (
            select(ClassTeacherRole.id)
            .where(ClassTeacherRole.class_id == class_id)
            .where(ClassTeacherRole.ad_object_guid == ad_object_guid)
            .where(_active_window_predicate(ts))
            .limit(1)
        )
        return (await self.session.execute(stmt)).scalar_one_or_none() is not None

    async def get(self, role_id: int) -> ClassTeacherRole | None:
        return await self.session.get(ClassTeacherRole, role_id)

    async def add(
        self,
        *,
        class_id: int,
        ad_object_guid: str,
        role: str,
        valid_from: datetime,
        valid_to: datetime | None,
        created_by: str | None,
    ) -> ClassTeacherRole:
        row = ClassTeacherRole(
            class_id=class_id,
            ad_object_guid=ad_object_guid,
            role=role,
            valid_from=valid_from,
            valid_to=valid_to,
            created_by=created_by,
        )
        self.session.add(row)
        await self.session.flush()
        return row

    async def end_now(self, row: ClassTeacherRole) -> ClassTeacherRole:
        """Soft-revoke: clamp valid_to to now (or earlier if already past)."""
        now = utcnow()
        if row.valid_to is None or row.valid_to > now:
            row.valid_to = now
            await self.session.flush()
        return row

    async def list_substitutions(self, school_ids: list[int] | None) -> list[SubstitutionRow]:
        """Return all stellvertretung roles joined with their class, scoped to school_ids.

        Admin passes school_ids=None to see all schools.
        """
        stmt = (
            select(ClassTeacherRole, SchoolClass.name, SchoolClass.school_id)
            .join(SchoolClass, SchoolClass.id == ClassTeacherRole.class_id)
            .where(ClassTeacherRole.role == KL_ROLE_STELLVERTRETUNG)
            .order_by(ClassTeacherRole.valid_from.desc(), ClassTeacherRole.id.desc())
        )
        if school_ids is not None:
            stmt = stmt.where(SchoolClass.school_id.in_(school_ids))
        rows = (await self.session.execute(stmt)).all()
        return [SubstitutionRow(role=r, class_name=name, school_id=sid) for r, name, sid in rows]
