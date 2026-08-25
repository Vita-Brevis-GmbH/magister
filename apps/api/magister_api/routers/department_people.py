"""``/departments/{id}/members`` + ``/managers`` — memberships and Kader roles.

Company-edition parallels to ``/classes/{id}/students`` and
``/classes/{id}/teachers``. Schulleitung-or-Admin (unit admin) manages both.
Scope is enforced via the department lookup.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from magister_api.auth.current_user import AuthenticatedUser
from magister_api.auth.rbac import require_schulleitung
from magister_api.config import Settings, get_settings
from magister_api.db import get_session
from magister_api.routers._helpers import _ip_request_id
from magister_api.schemas.department_people import (
    DepartmentMembershipCreate,
    DepartmentMembershipOut,
    ManagerRoleCreate,
    ManagerRoleOut,
)
from magister_api.services._user_enrich import fetch_user_labels, user_label_fields
from magister_api.services.department_people import (
    DepartmentNotInScopeError,
    DepartmentPeopleService,
    ManagerRoleNotFoundError,
    MembershipNotFoundError,
)

router = APIRouter(prefix="/departments/{department_id}", tags=["departments"])


# ---------- memberships ----------


@router.get("/members", response_model=list[DepartmentMembershipOut])
async def list_members(
    department_id: int,
    user: AuthenticatedUser = Depends(require_schulleitung),
    settings: Settings = Depends(get_settings),
    session: AsyncSession = Depends(get_session),
) -> list[DepartmentMembershipOut]:
    svc = DepartmentPeopleService(session, settings, user.to_scope())
    try:
        rows = await svc.list_members(department_id)
    except DepartmentNotInScopeError as exc:
        raise HTTPException(status_code=404, detail="department_not_found") from exc
    labels = await fetch_user_labels(session, (r.ad_object_guid for r in rows))
    return [
        DepartmentMembershipOut.model_validate(r).model_copy(
            update=dict(user_label_fields(labels.get(r.ad_object_guid)))
        )
        for r in rows
    ]


@router.post(
    "/members", response_model=DepartmentMembershipOut, status_code=status.HTTP_201_CREATED
)
async def add_member(
    department_id: int,
    payload: DepartmentMembershipCreate,
    request: Request,
    user: AuthenticatedUser = Depends(require_schulleitung),
    settings: Settings = Depends(get_settings),
    session: AsyncSession = Depends(get_session),
) -> DepartmentMembershipOut:
    svc = DepartmentPeopleService(session, settings, user.to_scope())
    ip, request_id = _ip_request_id(request)
    try:
        row = await svc.add_member(
            department_id=department_id,
            ad_object_guid=payload.ad_object_guid,
            valid_from=payload.valid_from,
            valid_to=payload.valid_to,
            ip=ip,
            request_id=request_id,
        )
    except DepartmentNotInScopeError as exc:
        raise HTTPException(status_code=404, detail="department_not_found") from exc
    return DepartmentMembershipOut.model_validate(row)


@router.delete("/members/{membership_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_member(
    department_id: int,
    membership_id: int,
    request: Request,
    user: AuthenticatedUser = Depends(require_schulleitung),
    settings: Settings = Depends(get_settings),
    session: AsyncSession = Depends(get_session),
) -> Response:
    svc = DepartmentPeopleService(session, settings, user.to_scope())
    ip, request_id = _ip_request_id(request)
    try:
        await svc.remove_member(
            department_id=department_id,
            membership_id=membership_id,
            ip=ip,
            request_id=request_id,
        )
    except DepartmentNotInScopeError as exc:
        raise HTTPException(status_code=404, detail="department_not_found") from exc
    except MembershipNotFoundError as exc:
        raise HTTPException(status_code=404, detail="membership_not_found") from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---------- manager (Kader) roles ----------


@router.get("/managers", response_model=list[ManagerRoleOut])
async def list_managers(
    department_id: int,
    user: AuthenticatedUser = Depends(require_schulleitung),
    settings: Settings = Depends(get_settings),
    session: AsyncSession = Depends(get_session),
) -> list[ManagerRoleOut]:
    svc = DepartmentPeopleService(session, settings, user.to_scope())
    try:
        rows = await svc.list_managers(department_id)
    except DepartmentNotInScopeError as exc:
        raise HTTPException(status_code=404, detail="department_not_found") from exc
    labels = await fetch_user_labels(session, (r.ad_object_guid for r in rows))
    return [
        ManagerRoleOut.model_validate(r).model_copy(
            update=dict(user_label_fields(labels.get(r.ad_object_guid)))
        )
        for r in rows
    ]


@router.post("/managers", response_model=ManagerRoleOut, status_code=status.HTTP_201_CREATED)
async def assign_manager(
    department_id: int,
    payload: ManagerRoleCreate,
    request: Request,
    user: AuthenticatedUser = Depends(require_schulleitung),
    settings: Settings = Depends(get_settings),
    session: AsyncSession = Depends(get_session),
) -> ManagerRoleOut:
    svc = DepartmentPeopleService(session, settings, user.to_scope())
    ip, request_id = _ip_request_id(request)
    try:
        row = await svc.assign_manager(
            department_id=department_id,
            ad_object_guid=payload.ad_object_guid,
            role=payload.role,
            valid_from=payload.valid_from,
            valid_to=payload.valid_to,
            ip=ip,
            request_id=request_id,
        )
    except DepartmentNotInScopeError as exc:
        raise HTTPException(status_code=404, detail="department_not_found") from exc
    return ManagerRoleOut.model_validate(row)


@router.delete("/managers/{role_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_manager(
    department_id: int,
    role_id: int,
    request: Request,
    user: AuthenticatedUser = Depends(require_schulleitung),
    settings: Settings = Depends(get_settings),
    session: AsyncSession = Depends(get_session),
) -> Response:
    svc = DepartmentPeopleService(session, settings, user.to_scope())
    ip, request_id = _ip_request_id(request)
    try:
        await svc.revoke_manager(
            department_id=department_id,
            role_id=role_id,
            ip=ip,
            request_id=request_id,
        )
    except DepartmentNotInScopeError as exc:
        raise HTTPException(status_code=404, detail="department_not_found") from exc
    except ManagerRoleNotFoundError as exc:
        raise HTTPException(status_code=404, detail="manager_role_not_found") from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


__all__ = ["router"]
