"""Aggregates the students a teacher is responsible for (KL or Fachlehrer)."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from magister_api.models.class_membership import ClassMembership
from magister_api.models.school_class import SchoolClass
from magister_api.repositories.class_memberships import ClassMembershipRepository
from magister_api.repositories.class_teachers import ClassTeacherRoleRepository
from magister_api.repositories.subject_teachers import SubjectTeacherRoleRepository
from magister_api.schemas.my_students import MyClassStudents, MyStudentBrief
from magister_api.services._user_enrich import fetch_user_labels


class MyStudentsService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.memberships = ClassMembershipRepository(session)
        self.kl = ClassTeacherRoleRepository(session)
        self.subject = SubjectTeacherRoleRepository(session)

    async def for_teacher(self, ad_object_guid: str) -> list[MyClassStudents]:
        kl_ids = await self.kl.active_class_ids_for_teacher(ad_object_guid)
        subject_ids = await self.subject.active_class_ids_for_teacher(ad_object_guid)
        class_ids = sorted(set(kl_ids) | set(subject_ids))

        # Collect (class, active members) first, then resolve every student
        # label in a single round-trip instead of one fetch per class.
        collected: list[tuple[SchoolClass, list[ClassMembership]]] = []
        for cid in class_ids:
            # scope-bypass: the caller's own active KL/Fachlehrer role on this
            # class IS the authorization; school_scope does not apply to teachers.
            cls = await self.session.get(SchoolClass, cid)
            if cls is None:
                continue
            members = await self.memberships.list_for_class(cid, only_active=True)
            collected.append((cls, members))

        labels = await fetch_user_labels(
            self.session, (m.ad_object_guid for _, members in collected for m in members)
        )

        out: list[MyClassStudents] = []
        for cls, members in collected:
            students: list[MyStudentBrief] = []
            for m in members:
                label = labels.get(m.ad_object_guid)
                students.append(
                    MyStudentBrief(
                        ad_object_guid=m.ad_object_guid,
                        display_name=label.display_name if label else None,
                        upn=label.upn if label else None,
                    )
                )
            out.append(
                MyClassStudents(
                    class_id=cls.id, name=cls.name, kuerzel=cls.kuerzel, students=students
                )
            )
        return out


__all__ = ["MyStudentsService"]
