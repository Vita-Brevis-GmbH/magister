"""Admin single-user lifecycle: create a real AD account / delete a user.

Distinct from the bulk student import (imports router) — this is the one-off
"neuen Benutzer anlegen" / "Benutzer löschen" surface. Admin-only.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from magister_api.ad.client import AdClient
from magister_api.ad.errors import AdUnavailableError
from magister_api.auth.current_user import AuthenticatedUser
from magister_api.auth.effective_settings import get_effective_settings
from magister_api.auth.rbac import require_admin
from magister_api.config import Settings
from magister_api.db import get_session
from magister_api.routers._helpers import _ip_request_id
from magister_api.routers.admin_sync import get_ad_client
from magister_api.schemas.user_admin import (
    AdUserCreateRequest,
    AdUserCreateResponse,
    AdUserDeleteResponse,
)
from magister_api.services.user_admin import UserAdminError, UserAdminService

router = APIRouter(prefix="/admin/ad-users", tags=["admin"])

_ERROR_STATUS = {
    "user_not_found": status.HTTP_404_NOT_FOUND,
    "user_not_disabled": status.HTTP_409_CONFLICT,
    "ou_not_configured": status.HTTP_409_CONFLICT,
    "invalid_ou_choice": status.HTTP_422_UNPROCESSABLE_ENTITY,
    "school_not_found": status.HTTP_404_NOT_FOUND,
}


@router.post("", response_model=AdUserCreateResponse, status_code=status.HTTP_201_CREATED)
async def create_ad_user(
    payload: AdUserCreateRequest,
    request: Request,
    user: AuthenticatedUser = Depends(require_admin),
    settings: Settings = Depends(get_effective_settings),
    session: AsyncSession = Depends(get_session),
    ad: AdClient = Depends(get_ad_client),
) -> AdUserCreateResponse:
    svc = UserAdminService(session, settings, ad)
    ip, request_id = _ip_request_id(request)
    try:
        created = await svc.create_user(
            given_name=payload.given_name,
            surname=payload.surname,
            sam_account_name=payload.sam_account_name,
            user_principal_name=payload.user_principal_name,
            mail=payload.mail,
            ou_key=payload.ou_key,
            school_id=payload.school_id,
            display_name=payload.display_name,
            force_change=payload.force_change,
            cannot_change_password=payload.cannot_change_password,
            password_never_expires=payload.password_never_expires,
            jahrgangsstufe=payload.jahrgangsstufe,
            actor_upn=user.upn,
            actor_object_guid=user.ad_object_guid,
            ip=ip,
            request_id=request_id,
        )
    except UserAdminError as exc:
        raise HTTPException(
            status_code=_ERROR_STATUS.get(exc.code, status.HTTP_400_BAD_REQUEST),
            detail=exc.code,
        ) from exc
    except AdUnavailableError as exc:
        # A duplicate DN/UPN/sAMAccountName also surfaces here.
        raise HTTPException(status_code=503, detail="ad_unavailable") from exc
    return AdUserCreateResponse(
        ad_object_guid=created.ad_object_guid, temp_password=created.temp_password
    )


@router.delete("/{ad_object_guid}", response_model=AdUserDeleteResponse)
async def delete_ad_user(
    ad_object_guid: str,
    request: Request,
    user: AuthenticatedUser = Depends(require_admin),
    settings: Settings = Depends(get_effective_settings),
    session: AsyncSession = Depends(get_session),
    ad: AdClient = Depends(get_ad_client),
) -> AdUserDeleteResponse:
    svc = UserAdminService(session, settings, ad)
    ip, request_id = _ip_request_id(request)
    try:
        ad_removed = await svc.delete_user(
            ad_object_guid=ad_object_guid,
            actor_upn=user.upn,
            actor_object_guid=user.ad_object_guid,
            ip=ip,
            request_id=request_id,
        )
    except UserAdminError as exc:
        raise HTTPException(
            status_code=_ERROR_STATUS.get(exc.code, status.HTTP_400_BAD_REQUEST),
            detail=exc.code,
        ) from exc
    except AdUnavailableError as exc:
        raise HTTPException(status_code=503, detail="ad_unavailable") from exc
    return AdUserDeleteResponse(ad_object_guid=ad_object_guid, ad_removed=ad_removed)


__all__ = ["router"]
