"""Per-class, per-student and per-teacher permissions.

Three RBAC tiers beyond the base roles:

- :func:`require_class_writer` for routes scoped to a class.
  Accepts admin / Schulleitung-of-class-school / active KL of that class.

- :func:`require_student_writer` for routes scoped to a student
  (``/students/{ad_object_guid}/...``). Accepts admin /
  Schulleitung or SMI of the student's school / active KL of any
  class the student is currently an active member of.

- :func:`require_teacher_writer` for routes scoped to a teacher
  (``/teachers/{ad_object_guid}/...``). Accepts admin / SMI of the
  teacher's school. Schulleitung and KL do *not* qualify — teacher
  user-management is an SMI capability.

In all cases outsiders get ``404`` (class_not_found / student_not_found /
teacher_not_found) to avoid leaking existence.
"""

from __future__ import annotations

from fastapi import Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from magister_api.auth.current_user import AuthenticatedUser, get_current_user
from magister_api.db import get_session
from magister_api.models.auth import AdUserCache
from magister_api.models.school_class import SchoolClass
from magister_api.repositories.class_memberships import ClassMembershipRepository
from magister_api.repositories.class_teachers import ClassTeacherRoleRepository


async def require_class_writer(
    class_id: int,
    user: AuthenticatedUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> AuthenticatedUser:
    """Ensure the caller may mutate ``class_id``.

    The class is looked up directly (no school-scope filter) so a KL whose
    only privilege is the class_teacher_roles row can still pass. The triage
    below replaces the scope check.
    """
    # scope-bypass: per-class permissions are derived from class.school_id
    # plus an active KL row; the class lookup must succeed for *any* viewer.
    cls = await session.get(SchoolClass, class_id)
    if cls is None:
        raise HTTPException(status_code=404, detail="class_not_found")

    if user.is_admin:
        return user

    if cls.school_id in user.school_scope:
        return user

    is_kl = await ClassTeacherRoleRepository(session).is_active_kl_of(
        ad_object_guid=user.ad_object_guid, class_id=class_id
    )
    if is_kl:
        return user

    # Mirror the cross-school 404 to avoid leaking that the class exists.
    raise HTTPException(status_code=404, detail="class_not_found")


async def require_student_writer(
    ad_object_guid: str,
    user: AuthenticatedUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> tuple[AuthenticatedUser, AdUserCache]:
    """Ensure the caller may mutate operations on ``ad_object_guid`` (the student).

    Returns ``(user, ad_user_cache_row)`` so the route handler can avoid a
    second DB roundtrip.
    """
    # scope-bypass: per-student permissions hinge on class memberships and
    # active KL roles; the AD-cache lookup itself must succeed for any viewer.
    student = await session.get(AdUserCache, ad_object_guid)
    if student is None:
        raise HTTPException(status_code=404, detail="student_not_found")

    if user.is_admin:
        return user, student

    # Schulleitung or SMI of the student's school?
    # Both roles populate ``school_scope`` via ``_roles_to_user``.
    if student.school_id is not None and student.school_id in user.school_scope:
        return user, student

    # Active KL of any class the student is currently an active member of?
    memberships = await ClassMembershipRepository(session).list_for_student(
        ad_object_guid, only_active=True
    )
    if memberships:
        kl_repo = ClassTeacherRoleRepository(session)
        for m in memberships:
            if await kl_repo.is_active_kl_of(
                ad_object_guid=user.ad_object_guid, class_id=m.class_id
            ):
                return user, student

    raise HTTPException(status_code=404, detail="student_not_found")


async def require_teacher_writer(
    ad_object_guid: str,
    user: AuthenticatedUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> tuple[AuthenticatedUser, AdUserCache]:
    """Ensure the caller may run admin-style operations on a teacher account.

    Accepts admin / SMI of the teacher's school. Schulleitung and KL do not
    qualify. Used by ``/teachers/{ad_object_guid}/password-reset``.

    Returns ``(user, ad_user_cache_row)``.
    """
    # scope-bypass: the AD-cache lookup itself must succeed before we can
    # decide who may write to the row.
    teacher = await session.get(AdUserCache, ad_object_guid)
    if teacher is None:
        raise HTTPException(status_code=404, detail="teacher_not_found")

    if user.is_admin:
        return user, teacher

    # SMI grants live in ``role_assignments`` per school; school_scope holds
    # them after ``_roles_to_user``. We additionally insist on the SMI role
    # being present so a Schulleitung-only user does not slip through.
    if (
        "smi" in user.roles
        and teacher.school_id is not None
        and teacher.school_id in user.school_scope
    ):
        return user, teacher

    raise HTTPException(status_code=404, detail="teacher_not_found")


__all__ = ["require_class_writer", "require_student_writer", "require_teacher_writer"]
