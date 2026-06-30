"""Admin-only lifecycle endpoints for the local break-glass account.

- ``GET    /admin/local-admin``         — status (never returns the hash)
- ``POST   /admin/local-admin/password`` — rotate the password
- ``PATCH  /admin/local-admin``         — toggle ``enabled``
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from magister_api.audit.service import AuditService
from magister_api.auth.current_user import AuthenticatedUser
from magister_api.auth.rbac import require_admin
from magister_api.config import Settings, get_settings
from magister_api.db import get_session
from magister_api.repositories.local_admin import LocalAdminRepository
from magister_api.routers._helpers import _ip_request_id
from magister_api.schemas.local_admin import (
    LocalAdminEnabledUpdate,
    LocalAdminOut,
    LocalAdminPasswordChangeRequest,
)
from magister_api.services.local_admin import LocalAdminService

router = APIRouter(prefix="/admin/local-admin", tags=["admin"])


@router.get("", response_model=LocalAdminOut)
async def get_local_admin(
    user: AuthenticatedUser = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
) -> LocalAdminOut:
    row = await LocalAdminRepository(session).get()
    if row is None:
        raise HTTPException(status_code=404, detail="local_admin_not_configured")
    return LocalAdminOut.model_validate(row)


@router.post("/password", status_code=status.HTTP_204_NO_CONTENT)
async def change_password(
    request: Request,
    payload: LocalAdminPasswordChangeRequest,
    user: AuthenticatedUser = Depends(require_admin),
    settings: Settings = Depends(get_settings),
    session: AsyncSession = Depends(get_session),
) -> None:
    svc = LocalAdminService(session)
    ok = await svc.change_password(
        current_password=payload.current_password,
        new_password=payload.new_password,
    )
    if not ok:
        raise HTTPException(status_code=400, detail="invalid_current_password")
    ip, request_id = _ip_request_id(request)
    await AuditService(session, settings).emit(
        action="local_admin_password_changed",
        target_kind="local_admin",
        target_id="1",
        actor_upn=user.upn,
        actor_object_guid=user.ad_object_guid,
        school_id=None,
        ip=ip,
        request_id=request_id,
        payload={},  # deliberately empty; allowlist forbids password fields anyway
    )


@router.patch("", response_model=LocalAdminOut)
async def update_local_admin(
    request: Request,
    payload: LocalAdminEnabledUpdate,
    user: AuthenticatedUser = Depends(require_admin),
    settings: Settings = Depends(get_settings),
    session: AsyncSession = Depends(get_session),
) -> LocalAdminOut:
    svc = LocalAdminService(session)
    row = await svc.set_enabled(payload.enabled)
    if row is None:
        raise HTTPException(status_code=404, detail="local_admin_not_configured")
    ip, request_id = _ip_request_id(request)
    await AuditService(session, settings).emit(
        action="local_admin_enabled_changed",
        target_kind="local_admin",
        target_id="1",
        actor_upn=user.upn,
        actor_object_guid=user.ad_object_guid,
        school_id=None,
        ip=ip,
        request_id=request_id,
        payload={"enabled": payload.enabled},
    )
    return LocalAdminOut.model_validate(row)


__all__ = ["router"]
