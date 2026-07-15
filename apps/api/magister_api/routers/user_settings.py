"""User-configuration surface for the manage tier (admin / Schulleitung / SMI).

- ``/admin/user-settings`` GET + PUT — the provisioning OUs, Zyklus boundaries,
  password-vault switch, group-catalog search base and the default AD group
  templates. Excludes OIDC / AD-connection / secret fields, which remain on the
  admin-only ``/admin/app-settings`` surface.
- ``/admin/ad-groups`` GET — the synced AD group catalog, so the GUI can offer
  group DNs as checkboxes instead of free-text.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from magister_api.auth.current_user import AuthenticatedUser
from magister_api.auth.rbac import require_manage
from magister_api.config import Settings, get_settings
from magister_api.db import get_session
from magister_api.repositories.ad_groups import AdGroupCatalogRepository
from magister_api.routers._helpers import _ip_request_id
from magister_api.schemas.ad_groups import AdGroupOut
from magister_api.schemas.user_settings import AdUserSettingsOut, AdUserSettingsUpdate
from magister_api.services.app_settings import AppSettingsService

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/user-settings", response_model=AdUserSettingsOut)
async def get_user_settings(
    user: AuthenticatedUser = Depends(require_manage),
    settings: Settings = Depends(get_settings),
    session: AsyncSession = Depends(get_session),
) -> AdUserSettingsOut:
    return await AppSettingsService(session, settings).get_user_config()


@router.put("/user-settings", response_model=AdUserSettingsOut)
async def update_user_settings(
    request: Request,
    payload: AdUserSettingsUpdate,
    user: AuthenticatedUser = Depends(require_manage),
    settings: Settings = Depends(get_settings),
    session: AsyncSession = Depends(get_session),
) -> AdUserSettingsOut:
    ip, request_id = _ip_request_id(request)
    return await AppSettingsService(session, settings).update_user_config(
        payload,
        actor_upn=user.upn,
        actor_object_guid=user.ad_object_guid,
        ip=ip,
        request_id=request_id,
    )


@router.get("/ad-groups", response_model=list[AdGroupOut])
async def list_ad_groups(
    user: AuthenticatedUser = Depends(require_manage),
    session: AsyncSession = Depends(get_session),
) -> list[AdGroupOut]:
    rows = await AdGroupCatalogRepository(session).list_all()
    return [AdGroupOut.model_validate(r) for r in rows]


__all__ = ["router"]
