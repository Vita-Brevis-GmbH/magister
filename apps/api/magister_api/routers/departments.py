"""``/departments`` CRUD (company edition). Schulleitung-or-Admin only.

Parallel to ``/classes`` for the school edition: the mid-level org unit
(Abteilung/Team). Scoped by ``school_id`` (the org-unit scope). See ADR-0008.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from magister_api.auth.current_user import AuthenticatedUser
from magister_api.auth.rbac import require_schulleitung
from magister_api.config import Settings, get_settings
from magister_api.db import get_session
from magister_api.repositories.department_memberships import DepartmentMembershipRepository
from magister_api.routers._helpers import _ip_request_id
from magister_api.schemas.department_people import UserDepartmentOut
from magister_api.schemas.departments import DepartmentCreate, DepartmentOut, DepartmentUpdate
from magister_api.services.department_people import DepartmentPeopleService
from magister_api.services.departments import (
    DepartmentNotFoundError,
    DepartmentPermissionError,
    DepartmentService,
)

router = APIRouter(prefix="/departments", tags=["departments"])


def _resolve_school_id(payload_school_id: int, user: AuthenticatedUser) -> int:
    """Unit-admin implicitly writes into their own (single) org unit; Admin passes it."""
    if user.is_admin:
        if payload_school_id <= 0:
            raise HTTPException(status_code=400, detail="school_id_required_for_admin")
        return payload_school_id
    if len(user.school_scope) != 1:
        raise HTTPException(status_code=400, detail="schulleitung_scope_must_be_exactly_one_school")
    derived = user.school_scope[0]
    if payload_school_id and payload_school_id != derived:
        raise HTTPException(status_code=403, detail="cross_school_write")
    return derived


@router.post("", response_model=DepartmentOut, status_code=status.HTTP_201_CREATED)
async def create_department(
    payload: DepartmentCreate,
    request: Request,
    user: AuthenticatedUser = Depends(require_schulleitung),
    settings: Settings = Depends(get_settings),
    session: AsyncSession = Depends(get_session),
) -> DepartmentOut:
    school_id = _resolve_school_id(payload.school_id, user)
    svc = DepartmentService(session, settings, user.to_scope())
    ip, request_id = _ip_request_id(request)
    try:
        row = await svc.create(
            school_id=school_id,
            name=payload.name,
            kuerzel=payload.kuerzel,
            details=payload.details,
            ip=ip,
            request_id=request_id,
        )
    except DepartmentPermissionError as exc:
        raise HTTPException(status_code=403, detail="cross_school_write") from exc
    return DepartmentOut.model_validate(row)


@router.get("", response_model=list[DepartmentOut])
async def list_departments(
    user: AuthenticatedUser = Depends(require_schulleitung),
    settings: Settings = Depends(get_settings),
    session: AsyncSession = Depends(get_session),
) -> list[DepartmentOut]:
    svc = DepartmentService(session, settings, user.to_scope())
    rows = await svc.list_active()
    counts = await DepartmentMembershipRepository(session).active_counts([r.id for r in rows])
    return [
        DepartmentOut.model_validate(r).model_copy(update={"member_count": counts.get(r.id, 0)})
        for r in rows
    ]


@router.get("/for-user/{ad_object_guid}", response_model=list[UserDepartmentOut])
async def list_user_departments(
    ad_object_guid: str,
    user: AuthenticatedUser = Depends(require_schulleitung),
    settings: Settings = Depends(get_settings),
    session: AsyncSession = Depends(get_session),
) -> list[UserDepartmentOut]:
    """The active departments a person belongs to, restricted to in-scope units.

    Powers the user-centric assignment view (#9): a person may sit in several
    departments at once, so this is a list.
    """
    svc = DepartmentPeopleService(session, settings, user.to_scope())
    pairs = await svc.list_user_memberships(ad_object_guid)
    return [
        UserDepartmentOut(
            membership_id=m.id,
            department_id=d.id,
            name=d.name,
            kuerzel=d.kuerzel,
            valid_from=m.valid_from,
        )
        for m, d in pairs
    ]


@router.get("/{department_id}", response_model=DepartmentOut)
async def get_department(
    department_id: int,
    user: AuthenticatedUser = Depends(require_schulleitung),
    settings: Settings = Depends(get_settings),
    session: AsyncSession = Depends(get_session),
) -> DepartmentOut:
    svc = DepartmentService(session, settings, user.to_scope())
    try:
        row = await svc.get(department_id)
    except DepartmentNotFoundError as exc:
        raise HTTPException(status_code=404, detail="department_not_found") from exc
    return DepartmentOut.model_validate(row)


@router.patch("/{department_id}", response_model=DepartmentOut)
async def patch_department(
    department_id: int,
    payload: DepartmentUpdate,
    request: Request,
    user: AuthenticatedUser = Depends(require_schulleitung),
    settings: Settings = Depends(get_settings),
    session: AsyncSession = Depends(get_session),
) -> DepartmentOut:
    svc = DepartmentService(session, settings, user.to_scope())
    ip, request_id = _ip_request_id(request)
    try:
        row = await svc.update(
            department_id=department_id,
            name=payload.name,
            kuerzel=payload.kuerzel,
            details=payload.details,
            ip=ip,
            request_id=request_id,
        )
    except DepartmentNotFoundError as exc:
        raise HTTPException(status_code=404, detail="department_not_found") from exc
    return DepartmentOut.model_validate(row)


@router.delete("/{department_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_department(
    department_id: int,
    request: Request,
    user: AuthenticatedUser = Depends(require_schulleitung),
    settings: Settings = Depends(get_settings),
    session: AsyncSession = Depends(get_session),
) -> Response:
    svc = DepartmentService(session, settings, user.to_scope())
    ip, request_id = _ip_request_id(request)
    try:
        await svc.archive(department_id=department_id, ip=ip, request_id=request_id)
    except DepartmentNotFoundError as exc:
        raise HTTPException(status_code=404, detail="department_not_found") from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


__all__ = ["router"]
