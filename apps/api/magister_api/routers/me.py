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
from magister_api.schemas.my_students import MyStudentsOut
from magister_api.schemas.user_preferences import UserPreferencesOut, UserPreferencesUpdate
from magister_api.services.my_students import MyStudentsService
from magister_api.services.user_preferences import UserPreferenceService

router = APIRouter(prefix="/me", tags=["me"])


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
