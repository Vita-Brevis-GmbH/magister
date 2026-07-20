"""Admin maintenance actions (demo-data purge, activity-log reset)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from magister_api.audit.service import AuditService
from magister_api.auth.current_user import AuthenticatedUser
from magister_api.auth.rbac import require_admin
from magister_api.config import Settings, get_settings
from magister_api.db import get_session
from magister_api.routers._helpers import _ip_request_id
from magister_api.schemas.user_admin import AuditResetResponse, DemoPurgeResponse
from magister_api.services.demo_data import DemoDataService
from magister_api.services.imports import purge_import_history

router = APIRouter(prefix="/admin", tags=["admin"])


@router.post("/demo-data/purge", response_model=DemoPurgeResponse)
async def purge_demo_data(
    request: Request,
    user: AuthenticatedUser = Depends(require_admin),
    settings: Settings = Depends(get_settings),
    session: AsyncSession = Depends(get_session),
) -> DemoPurgeResponse:
    """Delete the ``BSP`` demo school and everything under it. Idempotent."""
    ip, request_id = _ip_request_id(request)
    result = await DemoDataService(session, settings).purge(
        actor_upn=user.upn,
        actor_object_guid=user.ad_object_guid,
        ip=ip,
        request_id=request_id,
    )
    return DemoPurgeResponse(
        found=result.found,
        schools=result.schools,
        classes=result.classes,
        users=result.users,
    )


@router.post("/audit/reset", response_model=AuditResetResponse)
async def reset_activity_log(
    request: Request,
    user: AuthenticatedUser = Depends(require_admin),
    settings: Settings = Depends(get_settings),
    session: AsyncSession = Depends(get_session),
) -> AuditResetResponse:
    """Clear the whole activity overview before hand-over. Admin-only.

    Also clears the import history (jobs + staged rows) so the imports overview
    starts empty too. The reset itself is recorded, so the fresh log keeps a
    single entry documenting who cleared it and how much was removed.
    """
    ip, request_id = _ip_request_id(request)
    imports_deleted = await purge_import_history(session)
    deleted = await AuditService(session, settings).purge(
        actor_upn=user.upn,
        actor_object_guid=user.ad_object_guid,
        ip=ip,
        request_id=request_id,
        extra={"imports_deleted": imports_deleted},
    )
    return AuditResetResponse(deleted=deleted, imports_deleted=imports_deleted)


__all__ = ["router"]
