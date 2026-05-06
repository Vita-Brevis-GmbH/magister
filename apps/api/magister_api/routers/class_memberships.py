"""``/classes/{id}/students`` — assign / list / remove student class memberships.

Allowed actors per ``require_class_writer``:
- Admin
- Schulleitung of the class's school
- Active KL (haupt / co / stellvertretung) of the class
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from magister_api.auth.class_perm import require_class_writer
from magister_api.auth.current_user import AuthenticatedUser
from magister_api.config import Settings, get_settings
from magister_api.db import get_session
from magister_api.schemas.class_memberships import (
    ClassMembershipCreate,
    ClassMembershipOut,
)
from magister_api.services.class_memberships import (
    ClassMembershipService,
    ClassNotInScopeError,
    MembershipNotFoundError,
    OverlapError,
)

router = APIRouter(prefix="/classes/{class_id}/students", tags=["class-memberships"])


def _ip_request_id(request: Request) -> tuple[str | None, str]:
    return (
        getattr(request.state, "client_ip", None),
        getattr(request.state, "request_id", ""),
    )


@router.get("", response_model=list[ClassMembershipOut])
async def list_class_students(
    class_id: int,
    user: AuthenticatedUser = Depends(require_class_writer),
    settings: Settings = Depends(get_settings),
    session: AsyncSession = Depends(get_session),
) -> list[ClassMembershipOut]:
    svc = ClassMembershipService(session, settings, user.to_scope())
    try:
        rows = await svc.list_active(class_id)
    except ClassNotInScopeError as exc:
        raise HTTPException(status_code=404, detail="class_not_found") from exc
    return [ClassMembershipOut.model_validate(r) for r in rows]


@router.post("", response_model=ClassMembershipOut, status_code=status.HTTP_201_CREATED)
async def add_student_to_class(
    class_id: int,
    payload: ClassMembershipCreate,
    request: Request,
    user: AuthenticatedUser = Depends(require_class_writer),
    settings: Settings = Depends(get_settings),
    session: AsyncSession = Depends(get_session),
) -> ClassMembershipOut:
    svc = ClassMembershipService(session, settings, user.to_scope())
    ip, request_id = _ip_request_id(request)
    try:
        result = await svc.add_student(
            class_id=class_id,
            ad_object_guid=payload.ad_object_guid,
            valid_from=payload.valid_from,
            valid_to=payload.valid_to,
            ip=ip,
            request_id=request_id,
        )
    except ClassNotInScopeError as exc:
        raise HTTPException(status_code=404, detail="class_not_found") from exc
    except OverlapError as exc:
        raise HTTPException(status_code=409, detail="overlapping_membership") from exc
    return ClassMembershipOut.model_validate(result.membership)


@router.delete("/{membership_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_student_from_class(
    class_id: int,
    membership_id: int,
    request: Request,
    user: AuthenticatedUser = Depends(require_class_writer),
    settings: Settings = Depends(get_settings),
    session: AsyncSession = Depends(get_session),
) -> None:
    svc = ClassMembershipService(session, settings, user.to_scope())
    ip, request_id = _ip_request_id(request)
    try:
        await svc.remove_student(
            class_id=class_id,
            membership_id=membership_id,
            ip=ip,
            request_id=request_id,
        )
    except ClassNotInScopeError as exc:
        raise HTTPException(status_code=404, detail="class_not_found") from exc
    except MembershipNotFoundError as exc:
        raise HTTPException(status_code=404, detail="membership_not_found") from exc
    return None


__all__ = ["router"]
