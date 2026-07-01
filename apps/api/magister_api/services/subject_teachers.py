"""SubjectTeacherService — assign/revoke Fachlehrer with audit + scope guard."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from magister_api.audit.service import AuditService
from magister_api.config import Settings
from magister_api.models.subject_teacher_role import SubjectTeacherRole
from magister_api.repositories.base import ScopeContext
from magister_api.repositories.classes import ClassRepository
from magister_api.repositories.subject_teachers import SubjectTeacherRoleRepository


class SubjectTeacherNotFoundError(LookupError):
    pass


class ClassNotInScopeError(LookupError):
    """Caller cannot see the class. Mapped to 404 to avoid leaking existence."""


class SubjectTeacherService:
    def __init__(self, session: AsyncSession, settings: Settings, scope: ScopeContext) -> None:
        self.session = session
        self.settings = settings
        self.scope = scope
        self.classes_repo = ClassRepository(session, scope)
        self.repo = SubjectTeacherRoleRepository(session)
        self.audit = AuditService(session, settings)

    async def _scoped_class_or_404(self, class_id: int):
        cls = await self.classes_repo.get(class_id)
        if cls is None:
            raise ClassNotInScopeError(str(class_id))
        return cls

    async def list_for_class(self, class_id: int) -> list[SubjectTeacherRole]:
        await self._scoped_class_or_404(class_id)
        return await self.repo.list_for_class(class_id)

    async def assign(
        self,
        *,
        class_id: int,
        ad_object_guid: str,
        subject: str,
        valid_from: datetime,
        valid_to: datetime | None,
        ip: str | None,
        request_id: str,
    ) -> SubjectTeacherRole:
        cls = await self._scoped_class_or_404(class_id)
        row = await self.repo.add(
            class_id=class_id,
            ad_object_guid=ad_object_guid,
            subject=subject,
            valid_from=valid_from,
            valid_to=valid_to,
            created_by=self.scope.upn,
        )
        await self.audit.emit(
            action="subject_teacher_assigned",
            target_kind="subject_teacher_role",
            target_id=str(row.id),
            actor_upn=self.scope.upn,
            actor_object_guid=self.scope.ad_object_guid,
            school_id=cls.school_id,
            ip=ip,
            request_id=request_id,
            payload={
                "class_id": class_id,
                "teacher_object_guid": ad_object_guid,
                "subject": subject,
                "valid_from": valid_from.isoformat(),
                "valid_to": valid_to.isoformat() if valid_to else None,
            },
        )
        return row

    async def revoke(
        self,
        *,
        class_id: int,
        role_id: int,
        ip: str | None,
        request_id: str,
    ) -> SubjectTeacherRole:
        cls = await self._scoped_class_or_404(class_id)
        row = await self.repo.get(role_id)
        if row is None or row.class_id != class_id:
            raise SubjectTeacherNotFoundError(str(role_id))
        old_valid_to = row.valid_to
        row = await self.repo.end_now(row)
        await self.audit.emit(
            action="subject_teacher_revoked",
            target_kind="subject_teacher_role",
            target_id=str(row.id),
            actor_upn=self.scope.upn,
            actor_object_guid=self.scope.ad_object_guid,
            school_id=cls.school_id,
            ip=ip,
            request_id=request_id,
            payload={
                "class_id": class_id,
                "teacher_object_guid": row.ad_object_guid,
                "subject": row.subject,
                "old_valid_to": old_valid_to.isoformat() if old_valid_to else None,
                "new_valid_to": row.valid_to.isoformat() if row.valid_to else None,
            },
        )
        return row


__all__ = ["ClassNotInScopeError", "SubjectTeacherNotFoundError", "SubjectTeacherService"]
