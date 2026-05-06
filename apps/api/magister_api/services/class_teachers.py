"""ClassTeacherService — assign/revoke KL with audit emit and cross-school guard."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from magister_api.audit.service import AuditService
from magister_api.config import Settings
from magister_api.models.class_teacher_role import ClassTeacherRole
from magister_api.repositories.base import ScopeContext
from magister_api.repositories.class_teachers import ClassTeacherRoleRepository
from magister_api.repositories.classes import ClassRepository


class ClassTeacherNotFoundError(LookupError):
    pass


class ClassNotInScopeError(LookupError):
    """Caller cannot see the class. We map this to 404 to avoid leaking existence."""


class ClassTeacherService:
    def __init__(self, session: AsyncSession, settings: Settings, scope: ScopeContext) -> None:
        self.session = session
        self.settings = settings
        self.scope = scope
        self.classes_repo = ClassRepository(session, scope)
        self.repo = ClassTeacherRoleRepository(session)
        self.audit = AuditService(session, settings)

    async def _scoped_class_or_404(self, class_id: int):
        cls = await self.classes_repo.get(class_id)
        if cls is None:
            raise ClassNotInScopeError(str(class_id))
        return cls

    async def list_for_class(self, class_id: int) -> list[ClassTeacherRole]:
        await self._scoped_class_or_404(class_id)
        return await self.repo.list_for_class(class_id)

    async def is_active_kl_of(
        self,
        *,
        ad_object_guid: str,
        class_id: int,
        now: datetime | None = None,
    ) -> bool:
        """Predicate for downstream RBAC (#6, #7).

        Active KL = role row whose ``[valid_from, valid_to|+infty)`` window
        contains ``now``. Sub-role (haupt/co/stellvertretung) is irrelevant —
        all three are equally KL per SPEC.md §7 ("Co-KL", "Stellvertretung").
        """
        return await self.repo.is_active_kl_of(
            ad_object_guid=ad_object_guid, class_id=class_id, now=now
        )

    async def assign(
        self,
        *,
        class_id: int,
        ad_object_guid: str,
        role: str,
        valid_from: datetime,
        valid_to: datetime | None,
        ip: str | None,
        request_id: str,
    ) -> ClassTeacherRole:
        cls = await self._scoped_class_or_404(class_id)
        row = await self.repo.add(
            class_id=class_id,
            ad_object_guid=ad_object_guid,
            role=role,
            valid_from=valid_from,
            valid_to=valid_to,
            created_by=self.scope.upn,
        )
        await self.audit.emit(
            action="class_teacher_assigned",
            target_kind="class_teacher_role",
            target_id=str(row.id),
            actor_upn=self.scope.upn,
            actor_object_guid=self.scope.ad_object_guid,
            school_id=cls.school_id,
            ip=ip,
            request_id=request_id,
            payload={
                "class_id": class_id,
                "kl_object_guid": ad_object_guid,
                "role": role,
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
    ) -> ClassTeacherRole:
        cls = await self._scoped_class_or_404(class_id)
        row = await self.repo.get(role_id)
        if row is None or row.class_id != class_id:
            raise ClassTeacherNotFoundError(str(role_id))
        old_valid_to = row.valid_to
        row = await self.repo.end_now(row)
        await self.audit.emit(
            action="class_teacher_revoked",
            target_kind="class_teacher_role",
            target_id=str(row.id),
            actor_upn=self.scope.upn,
            actor_object_guid=self.scope.ad_object_guid,
            school_id=cls.school_id,
            ip=ip,
            request_id=request_id,
            payload={
                "class_id": class_id,
                "kl_object_guid": row.ad_object_guid,
                "role": row.role,
                "old_valid_to": old_valid_to.isoformat() if old_valid_to else None,
                "new_valid_to": row.valid_to.isoformat() if row.valid_to else None,
            },
        )
        return row
