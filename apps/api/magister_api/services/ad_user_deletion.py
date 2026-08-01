"""Hard-delete a user (student/teacher) from Magister after AD deletion.

AD is the source of truth: once a user's objectGUID is gone from AD, an admin
can remove them from Magister. This removes the cache row plus all Magister-side
data (class memberships, KL + subject roles, role assignments, preferences,
sessions). ``audit_events`` are intentionally kept for history, and a dedicated
``ad_user_deleted`` event is emitted.

Safety: only students/teachers are deletable (never admins). A user still
present in AD cannot be deleted — either the row is already flagged
``ad_missing_since`` by a full sync (trusted, allows offline cleanup) or a live
AD lookup must confirm the user is gone.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from magister_api.ad.client import AdClient
from magister_api.ad.errors import AdUnavailableError
from magister_api.audit.service import AuditService
from magister_api.config import Settings
from magister_api.models.auth import AdUserCache, RoleAssignment, Session
from magister_api.models.class_membership import ClassMembership
from magister_api.models.class_teacher_role import ClassTeacherRole
from magister_api.models.subject_teacher_role import SubjectTeacherRole
from magister_api.models.user_preferences import UserPreference
from magister_api.repositories.base import ScopeContext

DELETABLE_KINDS = frozenset({"student", "teacher"})

# Ordered so the audit payload and preview read naturally.
_CHILD_MODELS = (
    ("class_memberships", ClassMembership),
    ("class_teacher_roles", ClassTeacherRole),
    ("subject_teacher_roles", SubjectTeacherRole),
    ("role_assignments", RoleAssignment),
    ("user_preferences", UserPreference),
    ("sessions", Session),
)


class UserNotDeletableKindError(ValueError):
    """Attempt to delete an admin/local account via this path."""


class UserStillInAdError(ValueError):
    """The user is still present in AD — refuse deletion."""


class AdUnavailableForDeletionError(RuntimeError):
    """AD could not be reached to confirm absence."""


@dataclass(frozen=True)
class DeletionCounts:
    class_memberships: int = 0
    class_teacher_roles: int = 0
    subject_teacher_roles: int = 0
    role_assignments: int = 0
    user_preferences: int = 0
    sessions: int = 0


class AdUserDeletionService:
    def __init__(
        self, session: AsyncSession, settings: Settings, scope: ScopeContext, ad: AdClient
    ) -> None:
        self.session = session
        self.settings = settings
        self.scope = scope
        self.ad = ad
        self.audit = AuditService(session, settings)

    async def preview(self, target: AdUserCache) -> DeletionCounts:
        """Count the Magister-side rows that a delete would remove (no writes)."""
        counts: dict[str, int] = {}
        for key, model in _CHILD_MODELS:
            counts[key] = (
                await self.session.execute(
                    select(func.count())
                    .select_from(model)
                    .where(model.ad_object_guid == target.ad_object_guid)
                )
            ).scalar_one()
        return DeletionCounts(**counts)

    async def delete(
        self, *, target: AdUserCache, ip: str | None, request_id: str
    ) -> DeletionCounts:
        if target.kind not in DELETABLE_KINDS:
            raise UserNotDeletableKindError(target.kind)
        # Only delete users truly gone from AD. Trust a full-sync flag (offline
        # cleanup); otherwise verify live.
        if target.ad_missing_since is None:
            try:
                dn = await self.ad.find_user_dn(target.ad_object_guid)
            except AdUnavailableError as exc:
                raise AdUnavailableForDeletionError(str(exc)) from exc
            if dn is not None:
                raise UserStillInAdError(target.ad_object_guid)

        guid = target.ad_object_guid
        counts: dict[str, int] = {}
        for key, model in _CHILD_MODELS:
            counts[key] = (
                await self.session.execute(
                    select(func.count()).select_from(model).where(model.ad_object_guid == guid)
                )
            ).scalar_one()
            await self.session.execute(delete(model).where(model.ad_object_guid == guid))
        await self.session.execute(delete(AdUserCache).where(AdUserCache.ad_object_guid == guid))
        await self.session.flush()

        result = DeletionCounts(**counts)
        await self.audit.emit(
            action="ad_user_deleted",
            target_kind="ad_user",
            target_id=guid,
            actor_upn=self.scope.upn,
            actor_object_guid=self.scope.ad_object_guid,
            school_id=target.school_id,
            ip=ip,
            request_id=request_id,
            payload={"upn": target.upn, "kind": target.kind, **asdict(result)},
        )
        return result


__all__ = [
    "AdUnavailableForDeletionError",
    "AdUserDeletionService",
    "DeletionCounts",
    "UserNotDeletableKindError",
    "UserStillInAdError",
]
