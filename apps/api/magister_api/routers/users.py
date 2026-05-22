"""``/users`` — listing of cached AD users + PATCH for attribute edits."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from magister_api.ad.client import AdClient
from magister_api.ad.errors import AdUnavailableError
from magister_api.auth.class_perm import require_user_writer
from magister_api.auth.current_user import AuthenticatedUser
from magister_api.auth.rbac import require_role
from magister_api.config import Settings, get_settings
from magister_api.db import get_session
from magister_api.models.auth import AdUserCache
from magister_api.routers.admin_sync import get_ad_client
from magister_api.schemas.ad_users import AdUserListResponse, AdUserOut
from magister_api.schemas.user_attrs import UserAttributesUpdate
from magister_api.services.ad_users import AdUsersService
from magister_api.services.app_settings import AppSettingsService
from magister_api.services.user_attrs import (
    AdminOnlyFieldError,
    DomainAllowlistEmptyError,
    DomainNotAllowedError,
    UpnConflictError,
    UserAttributesService,
    UserNotInAdError,
)

router = APIRouter(prefix="/users", tags=["users"])


# KL-as-actor permission lands in #6 (kl_perm helper exists already in services.class_teachers).
# Until then, listing is open to Schulleitung-or-above and SMI; KL access is enabled in the next PR.
# SMI sees users from every school it is assigned to (per-school grants accumulate
# into ``school_scope``); the repository's scope filter does the rest.
require_listing = require_role("schulleitung", "smi")


@router.get("", response_model=AdUserListResponse)
async def list_users(
    user: AuthenticatedUser = Depends(require_listing),
    settings: Settings = Depends(get_settings),
    session: AsyncSession = Depends(get_session),
    kind: Annotated[
        str | None,
        Query(description="Filter by 'teacher' | 'student' | 'admin'."),
    ] = None,
    enabled: Annotated[bool | None, Query(description="Filter by AD enabled-flag.")] = None,
    search: Annotated[
        str | None,
        Query(min_length=1, max_length=64, description="Substring on UPN/given_name/surname."),
    ] = None,
    class_id: Annotated[
        int | None,
        Query(description="Filter to teachers with active KL role for this class."),
    ] = None,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> AdUserListResponse:
    svc = AdUsersService(session, settings, user.to_scope())
    listing = await svc.list(
        kind=kind,
        enabled=enabled,
        search=search,
        class_id=class_id,
        offset=offset,
        limit=limit,
    )
    return AdUserListResponse(
        items=[AdUserOut.model_validate(r) for r in listing.rows],
        total=listing.total,
        offset=offset,
        limit=limit,
        last_sync_at=listing.last_sync_at,
    )


def _ip_request_id(request: Request) -> tuple[str | None, str]:
    return (
        getattr(request.state, "client_ip", None),
        getattr(request.state, "request_id", ""),
    )


@router.patch("/{ad_object_guid}", response_model=AdUserOut)
async def patch_user_attributes(
    request: Request,
    payload: UserAttributesUpdate,
    user_and_target: tuple[AuthenticatedUser, AdUserCache] = Depends(require_user_writer),
    settings: Settings = Depends(get_settings),
    session: AsyncSession = Depends(get_session),
    ad: AdClient = Depends(get_ad_client),
) -> AdUserOut:
    """Edit the supported attributes of a cached AD user.

    Admin can change everything; SMI of the user's school can change
    everything *except* ``upn`` and ``sam_account_name`` (login-relevant —
    Schulträger-IT-only). AD-bound fields go through LDAP MODIFY; the
    Magister-only ``temp_device_name`` writes only to ``ad_user_cache``.
    """
    user, target = user_and_target

    settings_svc = AppSettingsService(session, settings)
    mail_domains = (await settings_svc.get_effective()).mail_domains

    svc = UserAttributesService(session, settings, user.to_scope(), ad)
    ip, request_id = _ip_request_id(request)
    try:
        await svc.update(
            target=target,
            payload=payload,
            mail_domains=mail_domains,
            ip=ip,
            request_id=request_id,
        )
    except AdminOnlyFieldError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"admin_only_field:{exc}",
        ) from exc
    except DomainAllowlistEmptyError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"mail_domains_not_configured:{exc}",
        ) from exc
    except DomainNotAllowedError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"domain_not_allowed:{exc}",
        ) from exc
    except UpnConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"upn_conflict:{exc}",
        ) from exc
    except UserNotInAdError as exc:
        raise HTTPException(status_code=409, detail="user_not_in_ad") from exc
    except AdUnavailableError as exc:
        raise HTTPException(status_code=503, detail="ad_unavailable") from exc

    # Re-fetch so the response shows the merged row.
    refreshed = await session.get(AdUserCache, target.ad_object_guid)
    assert refreshed is not None
    return AdUserOut.model_validate(refreshed)


__all__ = ["router"]
