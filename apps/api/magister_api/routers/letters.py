"""``/letters`` — generate parent-letter PDFs (M3 US-1).

Endpoints:
- ``POST /letters/{template}`` — body specifies student + optional context fields,
  response is a PDF stream.

RBAC: Admin + Schulleitung + SMI + KL of the student's class.
Currently routed through ``require_schulleitung`` (Admin + Schulleitung + SMI);
KL access can be added later if classroom teachers need to print directly.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from magister_api.auth.current_user import AuthenticatedUser
from magister_api.auth.rbac import require_schulleitung
from magister_api.config import Settings, get_settings
from magister_api.db import get_session
from magister_api.routers._helpers import _ip_request_id
from magister_api.schemas.common import ObjectGuid
from magister_api.services.letters import (
    ALLOWED_TEMPLATES,
    LetterContext,
    LetterService,
    MissingTemplateInputError,
    StudentNotFoundError,
    StudentNotInScopeError,
    UnknownTemplateError,
)

router = APIRouter(prefix="/letters", tags=["letters"])


class LetterRequest(BaseModel):
    student_guid: ObjectGuid
    # Optional context — required for some templates (the service validates).
    school_year: str | None = None
    first_day: str | None = None
    old_class_name: str | None = None
    effective_date: str | None = None
    temp_password: str | None = None


@router.post("/{template}")
async def generate_letter(
    template: str,
    payload: LetterRequest,
    request: Request,
    user: AuthenticatedUser = Depends(require_schulleitung),
    settings: Settings = Depends(get_settings),
    session: AsyncSession = Depends(get_session),
) -> Response:
    if template not in ALLOWED_TEMPLATES:
        raise HTTPException(status_code=404, detail="unknown_template")

    ctx = LetterContext(
        school_year=payload.school_year,
        first_day=payload.first_day,
        old_class_name=payload.old_class_name,
        effective_date=payload.effective_date,
        temp_password=payload.temp_password,
    )
    ip, request_id = _ip_request_id(request)
    svc = LetterService(session, settings, user.to_scope())

    try:
        html = await svc.prepare(
            template=template,
            student_guid=payload.student_guid,
            ctx=ctx,
            ip=ip,
            request_id=request_id,
        )
    except StudentNotFoundError as exc:
        raise HTTPException(status_code=404, detail="student_not_found") from exc
    except StudentNotInScopeError as exc:
        raise HTTPException(status_code=404, detail="student_not_found") from exc
    except UnknownTemplateError as exc:
        raise HTTPException(status_code=404, detail="unknown_template") from exc
    except MissingTemplateInputError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    # WeasyPrint is CPU-bound; keep it off the event loop.
    pdf_bytes = await run_in_threadpool(LetterService.html_to_pdf, html)

    return Response(
        content=pdf_bytes,
        status_code=status.HTTP_200_OK,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{template}.pdf"',
        },
    )


__all__ = ["router"]
