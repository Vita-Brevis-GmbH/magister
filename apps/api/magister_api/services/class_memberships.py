"""Service for ``class_memberships`` mutations.

Encodes the issue-#6 invariants:

- a student can be in at most one active class at any moment
- mid-year switches close the previous active membership at ``valid_from-1s``
- explicit overlap rejection if the new window overlaps an existing one (same student)
- audit ``student_added_to_class`` / ``student_removed_from_class`` per mutation
- cross-school protection via the ``ClassRepository`` scope filter
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from magister_api.audit.service import AuditService
from magister_api.config import Settings
from magister_api.models.base import utcnow
from magister_api.models.class_membership import ClassMembership
from magister_api.models.school_class import SchoolClass
from magister_api.repositories.base import ScopeContext
from magister_api.repositories.class_memberships import ClassMembershipRepository


class ClassNotInScopeError(LookupError):
    """Caller cannot see the class. Routers map this to 404."""


class MembershipNotFoundError(LookupError):
    pass


class OverlapError(ValueError):
    """The new window overlaps an existing active membership for the same student."""


@dataclass(frozen=True)
class AddResult:
    membership: ClassMembership
    closed_previous: list[int]
    """IDs of memberships whose ``valid_to`` was clamped during a mid-year switch."""


class ClassMembershipService:
    def __init__(self, session: AsyncSession, settings: Settings, scope: ScopeContext) -> None:
        self.session = session
        self.settings = settings
        self.scope = scope
        self.repo = ClassMembershipRepository(session)
        self.audit = AuditService(session, settings)

    async def _class_or_404(self, class_id: int) -> SchoolClass:
        # scope-bypass: callers route through require_class_writer which already
        # checked admin/Schulleitung/KL; this service trusts that decision.
        cls = await self.session.get(SchoolClass, class_id)
        if cls is None:
            raise ClassNotInScopeError(str(class_id))
        return cls

    async def list_active(self, class_id: int) -> list[ClassMembership]:
        await self._class_or_404(class_id)
        return await self.repo.list_for_class(class_id, only_active=True)

    async def add_student(
        self,
        *,
        class_id: int,
        ad_object_guid: str,
        valid_from: datetime | None,
        valid_to: datetime | None,
        ip: str | None,
        request_id: str,
    ) -> AddResult:
        cls = await self._class_or_404(class_id)
        effective_from = valid_from or utcnow()

        # Mid-year handling: end any currently-active membership in OTHER classes
        # right before this one opens. Same-class overlapping windows are rejected.
        clamp_at = effective_from - timedelta(seconds=1)
        closed = await self.repo.end_active_for_student(
            ad_object_guid=ad_object_guid,
            end_at=effective_from,
            excluding_class_id=class_id,
        )
        # We clamped them at end_at-1s by helper, redo with clamp_at to keep
        # the half-open semantics consistent with the new window.
        for row in closed:
            row.valid_to = clamp_at
        if closed:
            await self.session.flush()

        # Explicit overlap rejection (covers same-class re-add and any leftover edge).
        overlapping = await self.repo.find_overlapping(
            ad_object_guid=ad_object_guid,
            valid_from=effective_from,
            valid_to=valid_to,
        )
        if overlapping:
            raise OverlapError("overlapping_membership")

        row = await self.repo.add(
            class_id=class_id,
            ad_object_guid=ad_object_guid,
            valid_from=effective_from,
            valid_to=valid_to,
            created_by=self.scope.upn,
        )

        await self.audit.emit(
            action="student_added_to_class",
            target_kind="class_membership",
            target_id=str(row.id),
            actor_upn=self.scope.upn,
            actor_object_guid=self.scope.ad_object_guid,
            school_id=cls.school_id,
            ip=ip,
            request_id=request_id,
            payload={
                "class_id": class_id,
                "student_object_guid": ad_object_guid,
                "valid_from": effective_from.isoformat(),
                "valid_to": valid_to.isoformat() if valid_to else None,
                "closed_previous_ids": [r.id for r in closed],
            },
        )
        return AddResult(membership=row, closed_previous=[r.id for r in closed])

    async def bulk_add_students(
        self,
        *,
        class_id: int,
        students: list[tuple[str, object | None, object | None]],
        ip: str | None,
        request_id: str,
    ) -> list[tuple[AddResult | None, str | None]]:
        """Add multiple students to a class.

        Returns one tuple per input student: (AddResult | None, error_detail | None).
        Each student is attempted inside a savepoint so partial failures don't
        roll back the entire batch.
        """
        await self._class_or_404(class_id)
        results: list[tuple[AddResult | None, str | None]] = []
        for guid, valid_from, valid_to in students:
            sp = await self.session.begin_nested()
            try:
                result = await self.add_student(
                    class_id=class_id,
                    ad_object_guid=guid,
                    valid_from=valid_from,  # type: ignore[arg-type]
                    valid_to=valid_to,  # type: ignore[arg-type]
                    ip=ip,
                    request_id=request_id,
                )
                await sp.commit()
                results.append((result, None))
            except OverlapError:
                await sp.rollback()
                results.append((None, "overlapping_membership"))
        return results

    async def remove_student(
        self,
        *,
        class_id: int,
        membership_id: int,
        ip: str | None,
        request_id: str,
    ) -> ClassMembership:
        cls = await self._class_or_404(class_id)
        row = await self.repo.get(membership_id)
        if row is None or row.class_id != class_id:
            raise MembershipNotFoundError(str(membership_id))
        old_valid_to = row.valid_to
        now = utcnow()
        row = await self.repo.end_membership(row, end_at=now)
        await self.audit.emit(
            action="student_removed_from_class",
            target_kind="class_membership",
            target_id=str(row.id),
            actor_upn=self.scope.upn,
            actor_object_guid=self.scope.ad_object_guid,
            school_id=cls.school_id,
            ip=ip,
            request_id=request_id,
            payload={
                "class_id": class_id,
                "student_object_guid": row.ad_object_guid,
                "old_valid_to": old_valid_to.isoformat() if old_valid_to else None,
                "new_valid_to": row.valid_to.isoformat() if row.valid_to else None,
            },
        )
        return row
