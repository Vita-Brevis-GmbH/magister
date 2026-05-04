"""Per-class permissions.

For routes scoped to a specific class (``/classes/{class_id}/...``) we accept:

- Admin (``role='admin'``, school_id=NULL) — global write
- Schulleitung of the class's school (``role='schulleitung'`` with matching school_id)
- Active KL of that class (any sub-role; window-checked)

Anything else returns ``404 class_not_found`` — same response as a class that
doesn't exist, to avoid leaking existence to outsiders.
"""

from __future__ import annotations

from fastapi import Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from magister_api.auth.current_user import AuthenticatedUser, get_current_user
from magister_api.db import get_session
from magister_api.models.school_class import SchoolClass
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


__all__ = ["require_class_writer"]
