"""``/substitutions`` — cross-class view of all stellvertretung assignments.

Read: Admin sees all schools; Schulleitung/SMI see their own school scope.
Revoke: reuses the ClassTeacherService (same logic as DELETE /classes/{id}/teachers/{role_id}).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from magister_api.auth.current_user import AuthenticatedUser
from magister_api.auth.rbac import require_schulleitung
from magister_api.config import Settings, get_settings
from magister_api.db import get_session
from magister_api.repositories.class_teachers import ClassTeacherRoleRepository
from magister_api.routers._helpers import _ip_request_id
from magister_api.schemas.class_teachers import SubstitutionOut
from magister_api.services._user_enrich import fetch_user_labels
from magister_api.services.class_teachers import (
    ClassNotInScopeError,
    ClassTeacherNotFoundError,
    ClassTeacherService,
)

router = APIRouter(prefix="/substitutions", tags=["substitutions"])


@router.get("", response_model=list[SubstitutionOut])
async def list_substitutions(
    user: AuthenticatedUser = Depends(require_schulleitung),
    settings: Settings = Depends(get_settings),
    session: AsyncSession = Depends(get_session),
) -> list[SubstitutionOut]:
    """List all stellvertretung class-teacher roles within the caller's school scope."""
    repo = ClassTeacherRoleRepository(session)
    school_ids: list[int] | None = None if user.is_admin else list(user.school_scope)
    rows = await repo.list_substitutions(school_ids)

    labels = await fetch_user_labels(session, (r.role.ad_object_guid for r in rows))
    out: list[SubstitutionOut] = []
    for sub in rows:
        lbl = labels.get(sub.role.ad_object_guid)
        out.append(
            SubstitutionOut(
                id=sub.role.id,
                class_id=sub.role.class_id,
                ad_object_guid=sub.role.ad_object_guid,
                role=sub.role.role,
                valid_from=sub.role.valid_from,
                valid_to=sub.role.valid_to,
                created_at=sub.role.created_at,
                class_name=sub.class_name,
                school_id=sub.school_id,
                display_name=lbl.display_name if lbl else None,
                given_name=lbl.given_name if lbl else None,
                surname=lbl.surname if lbl else None,
                upn=lbl.upn if lbl else None,
            )
        )
    return out


@router.delete("/{role_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_substitution(
    role_id: int,
    request: Request,
    user: AuthenticatedUser = Depends(require_schulleitung),
    settings: Settings = Depends(get_settings),
    session: AsyncSession = Depends(get_session),
) -> None:
    """Revoke a stellvertretung by role_id without requiring class_id in the URL."""
    repo = ClassTeacherRoleRepository(session)
    row = await repo.get(role_id)
    if row is None:
        raise HTTPException(status_code=404, detail="class_teacher_role_not_found")

    svc = ClassTeacherService(session, settings, user.to_scope())
    ip, request_id = _ip_request_id(request)
    try:
        await svc.revoke(
            class_id=row.class_id,
            role_id=role_id,
            ip=ip,
            request_id=request_id,
        )
    except ClassNotInScopeError as exc:
        raise HTTPException(status_code=403, detail="forbidden") from exc
    except ClassTeacherNotFoundError as exc:
        raise HTTPException(status_code=404, detail="class_teacher_role_not_found") from exc
    return None


__all__ = ["router"]
