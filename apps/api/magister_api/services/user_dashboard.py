"""Builds the per-user dashboard aggregate (active classes + their KL)."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from magister_api.models.class_teacher_role import ClassTeacherRole
from magister_api.models.school_class import SchoolClass
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
        # Collect (class, active roles) first, then resolve all teacher labels in
        # a single round-trip (fetch_user_labels is built for one batch/response).
        collected: list[tuple[SchoolClass, list[ClassTeacherRole]]] = []
        for m in memberships:
            cls = await self.classes.get(m.class_id)
            if cls is None:
                continue
            roles = await self.teachers.list_active_for_class(cls.id)
            collected.append((cls, roles))

        labels = await fetch_user_labels(
            self.session, (r.ad_object_guid for _, roles in collected for r in roles)
        )

        out: list[UserClassOut] = []
        for cls, roles in collected:
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
                    jahrgangsstufe_bis=cls.jahrgangsstufe_bis,
                    teachers=teachers,
                )
            )
        return out


__all__ = ["UserDashboardService"]
