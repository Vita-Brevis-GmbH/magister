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
from magister_api.routers._helpers import _ip_request_id
from magister_api.schemas.class_memberships import (
    BulkClassMembershipCreate,
    BulkClassMembershipError,
    BulkClassMembershipResult,
    ClassMembershipCreate,
    ClassMembershipOut,
)
from magister_api.services._user_enrich import fetch_user_labels, user_label_fields
from magister_api.services.class_memberships import (
    ClassMembershipService,
    ClassNotInScopeError,
    MembershipNotFoundError,
    OverlapError,
)

router = APIRouter(prefix="/classes/{class_id}/students", tags=["class-memberships"])


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
    labels = await fetch_user_labels(session, (r.ad_object_guid for r in rows))
    return [
        ClassMembershipOut(
            id=r.id,
            class_id=r.class_id,
            ad_object_guid=r.ad_object_guid,
            valid_from=r.valid_from,
            valid_to=r.valid_to,
            created_at=r.created_at,
            **user_label_fields(labels.get(r.ad_object_guid)),
        )
        for r in rows
    ]


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


@router.post(
    "/bulk",
    response_model=BulkClassMembershipResult,
    status_code=status.HTTP_207_MULTI_STATUS,
)
async def bulk_add_students_to_class(
    class_id: int,
    payload: BulkClassMembershipCreate,
    request: Request,
    user: AuthenticatedUser = Depends(require_class_writer),
    settings: Settings = Depends(get_settings),
    session: AsyncSession = Depends(get_session),
) -> BulkClassMembershipResult:
    """Add multiple students to a class in one request.

    Each student is attempted individually; overlapping memberships are
    reported in ``errors`` while the rest are committed. Returns 207 so the
    caller can inspect the per-item result regardless of partial failures.
    """
    svc = ClassMembershipService(session, settings, user.to_scope())
    ip, request_id = _ip_request_id(request)
    try:
        raw = await svc.bulk_add_students(
            class_id=class_id,
            students=[(s.ad_object_guid, s.valid_from, s.valid_to) for s in payload.students],
            ip=ip,
            request_id=request_id,
        )
    except ClassNotInScopeError as exc:
        raise HTTPException(status_code=404, detail="class_not_found") from exc

    memberships: list[ClassMembershipOut] = []
    errors: list[BulkClassMembershipError] = []
    guids_added: list[str] = []

    for i, (entry, err) in enumerate(raw):
        if entry is not None:
            memberships.append(ClassMembershipOut.model_validate(entry.membership))
            guids_added.append(entry.membership.ad_object_guid)
        else:
            errors.append(
                BulkClassMembershipError(
                    ad_object_guid=payload.students[i].ad_object_guid,
                    detail=err or "unknown",
                )
            )

    # Enrich display labels for successfully added memberships.
    labels = await fetch_user_labels(session, iter(guids_added))
    for m in memberships:
        lbl = labels.get(m.ad_object_guid)
        if lbl:
            m.display_name = lbl.display_name
            m.given_name = lbl.given_name
            m.surname = lbl.surname
            m.upn = lbl.upn

    return BulkClassMembershipResult(added=len(memberships), memberships=memberships, errors=errors)


__all__ = ["router"]
