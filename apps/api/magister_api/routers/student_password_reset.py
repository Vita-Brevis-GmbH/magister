"""``POST /students/{ad_object_guid}/password-reset`` — KL resets student PW."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from magister_api.ad.client import AdClient
from magister_api.ad.errors import AdUnavailableError
from magister_api.auth.class_perm import require_student_writer
from magister_api.auth.current_user import AuthenticatedUser
from magister_api.config import Settings, get_settings
from magister_api.db import get_session
from magister_api.models.auth import AdUserCache
from magister_api.routers._helpers import _ip_request_id
from magister_api.routers.admin_sync import get_ad_client
from magister_api.routers.auth import limiter
from magister_api.schemas.password_reset import (
    StudentPasswordResetRequest,
    StudentPasswordResetResponse,
)
from magister_api.services.student_password_reset import (
    ManualPasswordPolicyError,
    StudentDisabledError,
    StudentNotInAdError,
    StudentPasswordResetService,
)

router = APIRouter(prefix="/students", tags=["student-password-reset"])


@router.post(
    "/{ad_object_guid}/password-reset",
    response_model=StudentPasswordResetResponse,
    status_code=status.HTTP_200_OK,
)
@limiter.limit("10/minute")  # pyright: ignore[reportUntypedFunctionDecorator]
async def reset_student_password(
    request: Request,
    payload: StudentPasswordResetRequest,
    user_and_student: tuple[AuthenticatedUser, AdUserCache] = Depends(require_student_writer),
    settings: Settings = Depends(get_settings),
    session: AsyncSession = Depends(get_session),
    ad: AdClient = Depends(get_ad_client),
) -> StudentPasswordResetResponse:
    user, student = user_and_student
    if student.kind != "student":
        # Reset endpoint is for students only; KL/admin reset is M2 territory.
        raise HTTPException(status_code=400, detail="not_a_student")

    svc = StudentPasswordResetService(session, settings, user.to_scope(), ad)
    ip, request_id = _ip_request_id(request)
    try:
        result = await svc.reset(
            student=student,
            mode=payload.mode,
            manual_password=payload.manual_password,
            force_change=payload.force_change,
            ip=ip,
            request_id=request_id,
        )
    except StudentDisabledError as exc:
        raise HTTPException(status_code=409, detail="student_disabled") from exc
    except StudentNotInAdError as exc:
        raise HTTPException(status_code=409, detail="student_not_in_ad") from exc
    except ManualPasswordPolicyError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except AdUnavailableError as exc:
        raise HTTPException(status_code=503, detail="ad_unavailable") from exc

    return StudentPasswordResetResponse(
        mode=result.mode,
        force_change=result.force_change,
        temp_password=result.temp_password,
    )


__all__ = ["router"]
