"""``POST /teachers/{ad_object_guid}/password-reset`` — SMI/admin resets teacher PW."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from magister_api.ad.client import AdClient
from magister_api.ad.errors import AdUnavailableError
from magister_api.auth.class_perm import require_teacher_writer
from magister_api.auth.current_user import AuthenticatedUser
from magister_api.config import Settings, get_settings
from magister_api.db import get_session
from magister_api.models.auth import AdUserCache
from magister_api.routers._helpers import _ip_request_id
from magister_api.routers.admin_sync import get_ad_client
from magister_api.routers.auth import limiter
from magister_api.schemas.password_reset import (
    TeacherPasswordResetRequest,
    TeacherPasswordResetResponse,
)
from magister_api.services.teacher_password_reset import (
    TeacherDisabledError,
    TeacherManualPasswordPolicyError,
    TeacherNotInAdError,
    TeacherPasswordResetService,
)

router = APIRouter(prefix="/teachers", tags=["teacher-password-reset"])


@router.post(
    "/{ad_object_guid}/password-reset",
    response_model=TeacherPasswordResetResponse,
    status_code=status.HTTP_200_OK,
)
@limiter.limit("10/minute")  # pyright: ignore[reportUntypedFunctionDecorator]
async def reset_teacher_password(
    request: Request,
    payload: TeacherPasswordResetRequest,
    user_and_teacher: tuple[AuthenticatedUser, AdUserCache] = Depends(require_teacher_writer),
    settings: Settings = Depends(get_settings),
    session: AsyncSession = Depends(get_session),
    ad: AdClient = Depends(get_ad_client),
) -> TeacherPasswordResetResponse:
    user, teacher = user_and_teacher
    if teacher.kind != "teacher":
        # /teachers/... is teachers-only. Admin accounts and students have
        # their own paths (the student endpoint, or none in M1).
        raise HTTPException(status_code=400, detail="not_a_teacher")

    svc = TeacherPasswordResetService(session, settings, user.to_scope(), ad)
    ip, request_id = _ip_request_id(request)
    try:
        result = await svc.reset(
            teacher=teacher,
            mode=payload.mode,
            manual_password=payload.manual_password,
            force_change=payload.force_change,
            ip=ip,
            request_id=request_id,
        )
    except TeacherDisabledError as exc:
        raise HTTPException(status_code=409, detail="teacher_disabled") from exc
    except TeacherNotInAdError as exc:
        raise HTTPException(status_code=409, detail="teacher_not_in_ad") from exc
    except TeacherManualPasswordPolicyError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except AdUnavailableError as exc:
        raise HTTPException(status_code=503, detail="ad_unavailable") from exc

    return TeacherPasswordResetResponse(
        mode=result.mode,
        force_change=result.force_change,
        temp_password=result.temp_password,
    )


__all__ = ["router"]
