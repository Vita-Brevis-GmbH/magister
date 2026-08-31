"""``POST /users/{ad_object_guid}/password-reset`` — reset a company / non-class
user's AD password.

The student/teacher endpoints stay kind-gated for the school flows; this one
covers everything else (company ``Benutzer`` and any future kind) so the reset
action is available in the company edition too. AD I/O runs through the injected
client, so in the strict split it crosses the AD-RPC boundary.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from magister_api.ad.client import AdClient
from magister_api.ad.errors import AdUnavailableError
from magister_api.auth.class_perm import require_user_writer
from magister_api.auth.current_user import AuthenticatedUser
from magister_api.config import Settings, get_settings
from magister_api.db import get_session
from magister_api.models.auth import AdUserCache
from magister_api.routers._helpers import _ip_request_id
from magister_api.routers.admin_sync import get_ad_client
from magister_api.routers.auth import limiter
from magister_api.schemas.password_reset import (
    UserPasswordResetRequest,
    UserPasswordResetResponse,
)
from magister_api.services.user_password_reset import (
    UserPasswordResetService,
    UserResetDisabledError,
    UserResetManualPasswordPolicyError,
    UserResetNotInAdError,
)

router = APIRouter(prefix="/users", tags=["user-password-reset"])


@router.post(
    "/{ad_object_guid}/password-reset",
    response_model=UserPasswordResetResponse,
    status_code=status.HTTP_200_OK,
)
@limiter.limit("10/minute")  # pyright: ignore[reportUntypedFunctionDecorator]
async def reset_user_password(
    request: Request,
    payload: UserPasswordResetRequest,
    user_and_target: tuple[AuthenticatedUser, AdUserCache] = Depends(require_user_writer),
    settings: Settings = Depends(get_settings),
    session: AsyncSession = Depends(get_session),
    ad: AdClient = Depends(get_ad_client),
) -> UserPasswordResetResponse:
    user, target = user_and_target
    if target.kind in ("student", "teacher"):
        # Those flows have their own kind-gated endpoints (distinct audit action).
        raise HTTPException(status_code=400, detail="use_kind_specific_reset")

    svc = UserPasswordResetService(session, settings, user.to_scope(), ad)
    ip, request_id = _ip_request_id(request)
    try:
        result = await svc.reset(
            target=target,
            mode=payload.mode,
            manual_password=payload.manual_password,
            force_change=payload.force_change,
            ip=ip,
            request_id=request_id,
        )
    except UserResetDisabledError as exc:
        raise HTTPException(status_code=409, detail="user_disabled") from exc
    except UserResetNotInAdError as exc:
        raise HTTPException(status_code=409, detail="user_not_in_ad") from exc
    except UserResetManualPasswordPolicyError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except AdUnavailableError as exc:
        raise HTTPException(status_code=503, detail="ad_unavailable") from exc

    return UserPasswordResetResponse(
        mode=result.mode,
        force_change=result.force_change,
        temp_password=result.temp_password,
    )


__all__ = ["router"]
