"""ClassMembership repository.

The active-window predicate matches :mod:`class_teacher_roles`:
``valid_from <= now < COALESCE(valid_to, +infty)``.

Scope is enforced one level up via the class lookup (ClassRepository); this
repo trusts that callers verified the class belongs to the user's scope.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from magister_api.models.base import utcnow
from magister_api.models.class_membership import ClassMembership


def _active_window_predicate(now: datetime):
    return and_(
        ClassMembership.valid_from <= now,
        or_(ClassMembership.valid_to.is_(None), ClassMembership.valid_to > now),
    )


def _current_or_upcoming_predicate(now: datetime):
    """Not-yet-ended memberships, including future starts (roster view).

    Drops the ``valid_from <= now`` bound so a student assigned now with a
    future start date (e.g. imported before the school year begins) still shows
    on the class roster. Ended memberships (``valid_to <= now``) are excluded.
    """
    return or_(ClassMembership.valid_to.is_(None), ClassMembership.valid_to > now)


def _windows_overlap(
    a_from: datetime,
    a_to: datetime | None,
    b_from: datetime,
    b_to: datetime | None,
) -> bool:
    """Half-open ``[from, to|+infty)`` overlap test."""
    if a_to is not None and a_to <= b_from:
        return False
    if b_to is not None and b_to <= a_from:
        return False
    return True


class ClassMembershipRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # --- Reads ---------------------------------------------------------------

    async def list_for_class(
        self,
        class_id: int,
        *,
        only_active: bool = True,
        include_upcoming: bool = False,
        now: datetime | None = None,
    ) -> list[ClassMembership]:
        ts = now or utcnow()
        stmt = select(ClassMembership).where(ClassMembership.class_id == class_id)
        if only_active:
            predicate = (
                _current_or_upcoming_predicate(ts)
                if include_upcoming
                else _active_window_predicate(ts)
            )
            stmt = stmt.where(predicate)
        stmt = stmt.order_by(ClassMembership.valid_from, ClassMembership.id)
        return list((await self.session.execute(stmt)).scalars().all())

    async def list_for_student(
        self, ad_object_guid: str, *, only_active: bool = True, now: datetime | None = None
    ) -> list[ClassMembership]:
        ts = now or utcnow()
        stmt = select(ClassMembership).where(ClassMembership.ad_object_guid == ad_object_guid)
        if only_active:
            stmt = stmt.where(_active_window_predicate(ts))
        stmt = stmt.order_by(ClassMembership.valid_from, ClassMembership.id)
        return list((await self.session.execute(stmt)).scalars().all())

    async def get(self, membership_id: int) -> ClassMembership | None:
        return await self.session.get(ClassMembership, membership_id)

    async def find_overlapping(
        self,
        *,
        ad_object_guid: str,
        valid_from: datetime,
        valid_to: datetime | None,
        exclude_id: int | None = None,
    ) -> list[ClassMembership]:
        """Return all rows whose window overlaps ``[valid_from, valid_to|+infty)``."""
        rows = await self.list_for_student(ad_object_guid, only_active=False, now=utcnow())
        return [
            r
            for r in rows
            if r.id != exclude_id
            and _windows_overlap(r.valid_from, r.valid_to, valid_from, valid_to)
        ]

    # --- Writes --------------------------------------------------------------

    async def add(
        self,
        *,
        class_id: int,
        ad_object_guid: str,
        valid_from: datetime,
        valid_to: datetime | None,
        created_by: str | None,
    ) -> ClassMembership:
        row = ClassMembership(
            class_id=class_id,
            ad_object_guid=ad_object_guid,
            valid_from=valid_from,
            valid_to=valid_to,
            created_by=created_by,
        )
        self.session.add(row)
        await self.session.flush()
        return row

    async def end_membership(self, row: ClassMembership, *, end_at: datetime) -> ClassMembership:
        """Clamp ``valid_to`` to ``end_at`` (no-op if already ended earlier)."""
        if row.valid_to is None or row.valid_to > end_at:
            row.valid_to = end_at
            await self.session.flush()
        return row

    async def end_active_for_student(
        self,
        *,
        ad_object_guid: str,
        end_at: datetime,
        excluding_class_id: int | None = None,
    ) -> list[ClassMembership]:
        """Mid-year helper: end every currently-active membership for the student.

        Returns the rows that were touched (their old ``valid_to`` is captured
        by the caller for audit if needed).
        """
        active = await self.list_for_student(ad_object_guid, only_active=True, now=end_at)
        clamp_to = end_at - timedelta(seconds=1)
        touched: list[ClassMembership] = []
        for row in active:
            if excluding_class_id is not None and row.class_id == excluding_class_id:
                continue
            await self.end_membership(row, end_at=clamp_to)
            touched.append(row)
        return touched
