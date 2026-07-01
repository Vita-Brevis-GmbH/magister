"""Admin-only ``/admin/app-settings`` GET + PUT.

Reads + writes the singleton ``app_settings`` row via :class:`AppSettingsService`.
Plaintext secrets are NEVER returned by ``GET``; ``PUT`` only updates a
secret when its payload field carries a non-empty string (omit / null = leave
the stored value alone).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from magister_api.auth.current_user import AuthenticatedUser
from magister_api.auth.rbac import require_admin
from magister_api.config import Settings, get_settings
from magister_api.db import get_session
from magister_api.routers._helpers import _ip_request_id
from magister_api.schemas.app_settings import AppSettingsOut, AppSettingsUpdate
from magister_api.services.app_settings import AppSettingsService

router = APIRouter(prefix="/admin/app-settings", tags=["admin"])


@router.get("", response_model=AppSettingsOut)
async def get_app_settings(
    user: AuthenticatedUser = Depends(require_admin),
    settings: Settings = Depends(get_settings),
    session: AsyncSession = Depends(get_session),
) -> AppSettingsOut:
    return await AppSettingsService(session, settings).get_redacted_for_api()


@router.put("", response_model=AppSettingsOut)
async def update_app_settings(
    request: Request,
    payload: AppSettingsUpdate,
    user: AuthenticatedUser = Depends(require_admin),
    settings: Settings = Depends(get_settings),
    session: AsyncSession = Depends(get_session),
) -> AppSettingsOut:
    ip, request_id = _ip_request_id(request)
    return await AppSettingsService(session, settings).update(
        payload,
        actor_upn=user.upn,
        actor_object_guid=user.ad_object_guid,
        ip=ip,
        request_id=request_id,
    )


__all__ = ["router"]
