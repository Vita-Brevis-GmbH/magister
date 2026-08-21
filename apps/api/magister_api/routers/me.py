"""``/me`` — self-service endpoints for the authenticated user.

Currently the per-user UI preferences (language, region, date/time formats).
Any authenticated user may read and write their own preferences.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from magister_api.auth.current_user import AuthenticatedUser, get_current_user
from magister_api.config import Settings, get_settings
from magister_api.db import get_session
from magister_api.routers._helpers import _ip_request_id
from magister_api.schemas.modules import ModuleOut, ModulesOut
from magister_api.schemas.my_students import MyStudentsOut
from magister_api.schemas.user_preferences import UserPreferencesOut, UserPreferencesUpdate
from magister_api.services.my_students import MyStudentsService
from magister_api.services.user_preferences import UserPreferenceService

router = APIRouter(prefix="/me", tags=["me"])


@router.get("/modules", response_model=ModulesOut)
async def my_modules(
    user: AuthenticatedUser = Depends(get_current_user),
) -> ModulesOut:
    """Feature modules enabled for this instance (M6 Phase 0, ADR-0008).

    Any authenticated user may read this; the frontend uses it to gate its
    navigation by module instead of hard-coding which entries exist. Phase 0
    returns every enabled module. Phase 1 filters by the instance profile +
    per-module toggles and adds nav metadata so a disabled module's menu
    entries drop out.
    """
    # Imported lazily: the registry imports the routers (this one included), so
    # a module-level import would create a circular import.
    from magister_api.modules.registry import enabled_modules

    return ModulesOut(
        modules=[ModuleOut(id=m.id, depends_on=list(m.depends_on)) for m in enabled_modules()]
    )


@router.get("/students", response_model=MyStudentsOut)
async def my_students(
    user: AuthenticatedUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> MyStudentsOut:
    """Active students in every class where the caller is an active KL or Fachlehrer."""
    classes = await MyStudentsService(session).for_teacher(user.ad_object_guid)
    return MyStudentsOut(classes=classes)


@router.get("/preferences", response_model=UserPreferencesOut)
async def get_my_preferences(
    user: AuthenticatedUser = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
    session: AsyncSession = Depends(get_session),
) -> UserPreferencesOut:
    return await UserPreferenceService(session, settings).get(user.ad_object_guid)


@router.put("/preferences", response_model=UserPreferencesOut)
async def put_my_preferences(
    payload: UserPreferencesUpdate,
    request: Request,
    user: AuthenticatedUser = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
    session: AsyncSession = Depends(get_session),
) -> UserPreferencesOut:
    ip, request_id = _ip_request_id(request)
    return await UserPreferenceService(session, settings).update(
        ad_object_guid=user.ad_object_guid,
        actor_upn=user.upn,
        payload=payload,
        ip=ip,
        request_id=request_id,
    )


__all__ = ["router"]
