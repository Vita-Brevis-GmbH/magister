"""``/classes/{id}/subject-teachers`` — assign/list/revoke Fachlehrer.

Schulleitung-or-Admin only (assigning a subject teacher is an organizational
decision, same as KL). The Fachlehrer themselves gain student-password-reset
for that class via ``auth.class_perm``.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from magister_api.auth.current_user import AuthenticatedUser
from magister_api.auth.rbac import require_schulleitung
from magister_api.config import Settings, get_settings
from magister_api.db import get_session
from magister_api.routers._helpers import _ip_request_id
from magister_api.schemas.subject_teachers import SubjectTeacherCreate, SubjectTeacherOut
from magister_api.services._user_enrich import fetch_user_labels, user_label_fields
from magister_api.services.subject_teachers import (
    ClassNotInScopeError,
    SubjectTeacherNotFoundError,
    SubjectTeacherService,
)

router = APIRouter(prefix="/classes/{class_id}/subject-teachers", tags=["subject-teachers"])


@router.get("", response_model=list[SubjectTeacherOut])
async def list_subject_teachers(
    class_id: int,
    user: AuthenticatedUser = Depends(require_schulleitung),
    settings: Settings = Depends(get_settings),
    session: AsyncSession = Depends(get_session),
) -> list[SubjectTeacherOut]:
    svc = SubjectTeacherService(session, settings, user.to_scope())
    try:
        rows = await svc.list_for_class(class_id)
    except ClassNotInScopeError as exc:
        raise HTTPException(status_code=404, detail="class_not_found") from exc
    labels = await fetch_user_labels(session, (r.ad_object_guid for r in rows))
    return [
        SubjectTeacherOut(
            id=r.id,
            class_id=r.class_id,
            ad_object_guid=r.ad_object_guid,
            subject=r.subject,
            valid_from=r.valid_from,
            valid_to=r.valid_to,
            created_at=r.created_at,
            **user_label_fields(labels.get(r.ad_object_guid)),
        )
        for r in rows
    ]


@router.post("", response_model=SubjectTeacherOut, status_code=status.HTTP_201_CREATED)
async def assign_subject_teacher(
    class_id: int,
    payload: SubjectTeacherCreate,
    request: Request,
    user: AuthenticatedUser = Depends(require_schulleitung),
    settings: Settings = Depends(get_settings),
    session: AsyncSession = Depends(get_session),
) -> SubjectTeacherOut:
    svc = SubjectTeacherService(session, settings, user.to_scope())
    ip, request_id = _ip_request_id(request)
    try:
        row = await svc.assign(
            class_id=class_id,
            ad_object_guid=payload.ad_object_guid,
            subject=payload.subject,
            valid_from=payload.valid_from,
            valid_to=payload.valid_to,
            ip=ip,
            request_id=request_id,
        )
    except ClassNotInScopeError as exc:
        raise HTTPException(status_code=404, detail="class_not_found") from exc
    return SubjectTeacherOut.model_validate(row)


@router.delete("/{role_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_subject_teacher(
    class_id: int,
    role_id: int,
    request: Request,
    user: AuthenticatedUser = Depends(require_schulleitung),
    settings: Settings = Depends(get_settings),
    session: AsyncSession = Depends(get_session),
) -> None:
    svc = SubjectTeacherService(session, settings, user.to_scope())
    ip, request_id = _ip_request_id(request)
    try:
        await svc.revoke(class_id=class_id, role_id=role_id, ip=ip, request_id=request_id)
    except ClassNotInScopeError as exc:
        raise HTTPException(status_code=404, detail="class_not_found") from exc
    except SubjectTeacherNotFoundError as exc:
        raise HTTPException(status_code=404, detail="subject_teacher_role_not_found") from exc
    return None


__all__ = ["router"]
