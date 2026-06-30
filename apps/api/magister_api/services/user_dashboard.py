"""Builds the per-user dashboard aggregate (active classes + their KL)."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from magister_api.repositories.base import ScopeContext
from magister_api.repositories.class_memberships import ClassMembershipRepository
from magister_api.repositories.class_teachers import ClassTeacherRoleRepository
from magister_api.repositories.classes import ClassRepository
from magister_api.schemas.user_dashboard import ClassTeacherBrief, UserClassOut
from magister_api.services._user_enrich import fetch_user_labels


class UserDashboardService:
    def __init__(self, session: AsyncSession, scope: ScopeContext) -> None:
        self.session = session
        self.memberships = ClassMembershipRepository(session)
        self.classes = ClassRepository(session, scope)
        self.teachers = ClassTeacherRoleRepository(session)

    async def for_user(self, ad_object_guid: str) -> list[UserClassOut]:
        """Active classes of the user, each with its active class-teachers.

        The class lookup goes through the scope-filtered ClassRepository, so a
        class outside the caller's scope is silently skipped (defence in depth;
        the caller is already scope-checked against the target user).
        """
        memberships = await self.memberships.list_for_student(ad_object_guid, only_active=True)
        out: list[UserClassOut] = []
        for m in memberships:
            cls = await self.classes.get(m.class_id)
            if cls is None:
                continue
            roles = await self.teachers.list_active_for_class(cls.id)
            labels = await fetch_user_labels(self.session, (r.ad_object_guid for r in roles))
            teachers: list[ClassTeacherBrief] = []
            for r in roles:
                label = labels.get(r.ad_object_guid)
                teachers.append(
                    ClassTeacherBrief(
                        ad_object_guid=r.ad_object_guid,
                        display_name=label.display_name if label else None,
                        upn=label.upn if label else None,
                        role=r.role,
                    )
                )
            out.append(
                UserClassOut(
                    class_id=cls.id,
                    name=cls.name,
                    kuerzel=cls.kuerzel,
                    jahrgangsstufe=cls.jahrgangsstufe,
                    teachers=teachers,
                )
            )
        return out


__all__ = ["UserDashboardService"]
