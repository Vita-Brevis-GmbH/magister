"""``/company/onboard`` + ``/company/offboard`` — company on-/offboarding.

Onboarding places an existing user into a department (+ optional Kader role);
offboarding ends all of a person's active memberships and manager roles within
the actor's scope. Schulleitung-or-Admin (unit admin). AD account enable/disable
stays the platform's ``PATCH /users/{guid}/status`` endpoint.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from magister_api.auth.current_user import AuthenticatedUser
from magister_api.auth.rbac import require_schulleitung
from magister_api.config import Settings, get_settings
from magister_api.db import get_session
from magister_api.routers._helpers import _ip_request_id
from magister_api.schemas.company_lifecycle import (
    OffboardRequest,
    OffboardResult,
    OnboardRequest,
    OnboardResult,
)
from magister_api.services.company_lifecycle import (
    CompanyLifecycleService,
    DepartmentNotInScopeError,
)

router = APIRouter(prefix="/company", tags=["company"])


@router.post("/onboard", response_model=OnboardResult, status_code=status.HTTP_201_CREATED)
async def onboard(
    payload: OnboardRequest,
    request: Request,
    user: AuthenticatedUser = Depends(require_schulleitung),
    settings: Settings = Depends(get_settings),
    session: AsyncSession = Depends(get_session),
) -> OnboardResult:
    svc = CompanyLifecycleService(session, settings, user.to_scope())
    ip, request_id = _ip_request_id(request)
    try:
        membership, manager_role = await svc.onboard(
            ad_object_guid=payload.ad_object_guid,
            department_id=payload.department_id,
            role=payload.role,
            valid_from=payload.valid_from,
            ip=ip,
            request_id=request_id,
        )
    except DepartmentNotInScopeError as exc:
        raise HTTPException(status_code=404, detail="department_not_found") from exc
    return OnboardResult(
        ad_object_guid=payload.ad_object_guid,
        department_id=payload.department_id,
        membership_id=membership.id,
        manager_role_id=manager_role.id if manager_role is not None else None,
    )


@router.post("/offboard", response_model=OffboardResult)
async def offboard(
    payload: OffboardRequest,
    request: Request,
    user: AuthenticatedUser = Depends(require_schulleitung),
    settings: Settings = Depends(get_settings),
    session: AsyncSession = Depends(get_session),
) -> OffboardResult:
    svc = CompanyLifecycleService(session, settings, user.to_scope())
    ip, request_id = _ip_request_id(request)
    memberships_ended, roles_revoked = await svc.offboard(
        ad_object_guid=payload.ad_object_guid,
        ip=ip,
        request_id=request_id,
    )
    return OffboardResult(
        ad_object_guid=payload.ad_object_guid,
        memberships_ended=memberships_ended,
        manager_roles_revoked=roles_revoked,
    )


__all__ = ["router"]
