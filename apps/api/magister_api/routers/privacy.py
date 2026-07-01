"""``/privacy`` — Subject-Access export per user (revDSG Art. 25, M3 US-4/US-5).

Endpoints:
- ``GET /privacy/subject-access/{guid}`` — JSON report
- ``GET /privacy/subject-access/{guid}/export.csv`` — same data as CSV

RBAC: Admin overall + Schulleitung/SMI for users in their own school. KL has
no access. Every fetch self-audits as ``subject_access_export``.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from magister_api.auth.current_user import AuthenticatedUser
from magister_api.auth.rbac import require_schulleitung
from magister_api.config import Settings, get_settings
from magister_api.db import get_session
from magister_api.routers._helpers import _ip_request_id
from magister_api.services.privacy import (
    PrivacyService,
    SubjectAccessReport,
    SubjectNotFoundError,
    SubjectNotInScopeError,
    render_csv,
)

router = APIRouter(prefix="/privacy", tags=["privacy"])


class SubjectAccessOut(BaseModel):
    user: dict[str, Any]
    school: dict[str, Any] | None
    memberships: list[dict[str, Any]]
    teacher_roles: list[dict[str, Any]]
    audit_events: list[dict[str, Any]]


@router.get("/subject-access/{guid}", response_model=SubjectAccessOut)
async def subject_access(
    guid: str,
    request: Request,
    user: AuthenticatedUser = Depends(require_schulleitung),
    settings: Settings = Depends(get_settings),
    session: AsyncSession = Depends(get_session),
) -> SubjectAccessOut:
    svc = PrivacyService(session, settings, user.to_scope())
    ip, request_id = _ip_request_id(request)
    try:
        report = await svc.subject_access(target_guid=guid, ip=ip, request_id=request_id)
    except SubjectNotFoundError as exc:
        raise HTTPException(status_code=404, detail="subject_not_found") from exc
    except SubjectNotInScopeError as exc:
        # Hide existence cross-school.
        raise HTTPException(status_code=404, detail="subject_not_found") from exc
    return SubjectAccessOut(
        user=report.user,
        school=report.school,
        memberships=report.memberships,
        teacher_roles=report.teacher_roles,
        audit_events=report.audit_events,
    )


@router.get("/subject-access/{guid}/export.csv", response_class=PlainTextResponse)
async def subject_access_csv(
    guid: str,
    request: Request,
    user: AuthenticatedUser = Depends(require_schulleitung),
    settings: Settings = Depends(get_settings),
    session: AsyncSession = Depends(get_session),
) -> PlainTextResponse:
    svc = PrivacyService(session, settings, user.to_scope())
    ip, request_id = _ip_request_id(request)
    try:
        report: SubjectAccessReport = await svc.subject_access(
            target_guid=guid, ip=ip, request_id=request_id
        )
    except SubjectNotFoundError as exc:
        raise HTTPException(status_code=404, detail="subject_not_found") from exc
    except SubjectNotInScopeError as exc:
        raise HTTPException(status_code=404, detail="subject_not_found") from exc

    body = render_csv(report)
    safe_id = guid.replace("/", "_")
    return PlainTextResponse(
        content=body,
        status_code=status.HTTP_200_OK,
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="subject-access-{safe_id}.csv"',
        },
    )


__all__ = ["router"]
