"""``/classes/{id}/teachers`` — assign/list/revoke Klassenlehrer roles.

Schulleitung-or-Admin only (assigning KL is an organizational decision).
The KL itself doesn't manage their own assignment — they just get to act on
the class via #6/#7 once the role exists.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from magister_api.auth.current_user import AuthenticatedUser
from magister_api.auth.rbac import require_schulleitung
from magister_api.config import Settings, get_settings
from magister_api.db import get_session
from magister_api.schemas.class_teachers import ClassTeacherCreate, ClassTeacherOut
from magister_api.services._user_enrich import fetch_user_labels
from magister_api.services.class_teachers import (
    ClassNotInScopeError,
    ClassTeacherNotFoundError,
    ClassTeacherService,
)

router = APIRouter(prefix="/classes/{class_id}/teachers", tags=["class-teachers"])


def _ip_request_id(request: Request) -> tuple[str | None, str]:
    return (
        getattr(request.state, "client_ip", None),
        getattr(request.state, "request_id", ""),
    )


@router.get("", response_model=list[ClassTeacherOut])
async def list_class_teachers(
    class_id: int,
    user: AuthenticatedUser = Depends(require_schulleitung),
    settings: Settings = Depends(get_settings),
    session: AsyncSession = Depends(get_session),
) -> list[ClassTeacherOut]:
    svc = ClassTeacherService(session, settings, user.to_scope())
    try:
        rows = await svc.list_for_class(class_id)
    except ClassNotInScopeError as exc:
        raise HTTPException(status_code=404, detail="class_not_found") from exc
    labels = await fetch_user_labels(session, (r.ad_object_guid for r in rows))
    out: list[ClassTeacherOut] = []
    for r in rows:
        lbl = labels.get(r.ad_object_guid)
        out.append(
            ClassTeacherOut(
                id=r.id,
                class_id=r.class_id,
                ad_object_guid=r.ad_object_guid,
                role=r.role,
                valid_from=r.valid_from,
                valid_to=r.valid_to,
                created_at=r.created_at,
                display_name=lbl.display_name if lbl else None,
                given_name=lbl.given_name if lbl else None,
                surname=lbl.surname if lbl else None,
                upn=lbl.upn if lbl else None,
            )
        )
    return out


@router.post("", response_model=ClassTeacherOut, status_code=status.HTTP_201_CREATED)
async def assign_class_teacher(
    class_id: int,
    payload: ClassTeacherCreate,
    request: Request,
    user: AuthenticatedUser = Depends(require_schulleitung),
    settings: Settings = Depends(get_settings),
    session: AsyncSession = Depends(get_session),
) -> ClassTeacherOut:
    svc = ClassTeacherService(session, settings, user.to_scope())
    ip, request_id = _ip_request_id(request)
    try:
        row = await svc.assign(
            class_id=class_id,
            ad_object_guid=payload.ad_object_guid,
            role=payload.role,
            valid_from=payload.valid_from,
            valid_to=payload.valid_to,
            ip=ip,
            request_id=request_id,
        )
    except ClassNotInScopeError as exc:
        raise HTTPException(status_code=404, detail="class_not_found") from exc
    return ClassTeacherOut.model_validate(row)


@router.delete("/{role_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_class_teacher(
    class_id: int,
    role_id: int,
    request: Request,
    user: AuthenticatedUser = Depends(require_schulleitung),
    settings: Settings = Depends(get_settings),
    session: AsyncSession = Depends(get_session),
) -> None:
    svc = ClassTeacherService(session, settings, user.to_scope())
    ip, request_id = _ip_request_id(request)
    try:
        await svc.revoke(class_id=class_id, role_id=role_id, ip=ip, request_id=request_id)
    except ClassNotInScopeError as exc:
        raise HTTPException(status_code=404, detail="class_not_found") from exc
    except ClassTeacherNotFoundError as exc:
        raise HTTPException(status_code=404, detail="class_teacher_role_not_found") from exc
    return None


__all__ = ["router"]
