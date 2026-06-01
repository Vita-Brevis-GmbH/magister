"""``/imports`` — CSV-Import Stage→Diff→Apply workflow (M3 US-2).

Endpoints
---------
- ``GET  /imports/templates/{kind}.csv`` — Template-Download with example rows
- ``GET  /imports`` — List jobs in the caller's school scope
- ``POST /imports?kind=…&school_id=…`` — Upload CSV → returns staged job (status=staged)
- ``GET  /imports/{id}`` — Detail with all staged rows and per-action counts
- ``POST /imports/{id}/apply`` — Apply staged actions (one savepoint per row)
- ``DELETE /imports/{id}`` — Cancel a staged job

RBAC: Admin + Schulleitung. KL has no access.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request, UploadFile, status
from fastapi.responses import PlainTextResponse
from sqlalchemy.ext.asyncio import AsyncSession

from magister_api.auth.current_user import AuthenticatedUser
from magister_api.auth.rbac import require_schulleitung
from magister_api.config import Settings, get_settings
from magister_api.db import get_session
from magister_api.models.import_job import ALLOWED_IMPORT_KINDS
from magister_api.schemas.imports import (
    ImportJobDetailOut,
    ImportJobOut,
    ImportStagedRowOut,
)
from magister_api.services.imports import (
    ImportJobBadStateError,
    ImportJobNotFoundError,
    ImportService,
    InvalidCsvError,
    render_template,
)

router = APIRouter(prefix="/imports", tags=["imports"])


def _ip_request_id(request: Request) -> tuple[str | None, str]:
    return (
        getattr(request.state, "client_ip", None),
        getattr(request.state, "request_id", ""),
    )


def _resolve_school_id(payload_school_id: int | None, user: AuthenticatedUser) -> int:
    """Same rule as /classes: Schulleitung writes into their own school; Admin must pass it."""
    if user.is_admin:
        if payload_school_id is None:
            raise HTTPException(status_code=400, detail="school_id_required_for_admin")
        return payload_school_id
    scope = list(user.school_scope)
    if not scope:
        raise HTTPException(status_code=403, detail="forbidden")
    if payload_school_id is not None and payload_school_id not in scope:
        raise HTTPException(status_code=403, detail="forbidden")
    return scope[0]


@router.get("/templates/{kind}.csv", response_class=PlainTextResponse)
async def get_template(
    kind: str,
    user: AuthenticatedUser = Depends(require_schulleitung),
) -> PlainTextResponse:
    """Download a CSV template with the expected header and 2-3 example rows."""
    if kind not in ALLOWED_IMPORT_KINDS:
        raise HTTPException(status_code=404, detail="unknown_kind")
    body = render_template(kind)
    _ = user  # auth gate only
    return PlainTextResponse(
        content=body,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{kind}.csv"'},
    )


@router.get("", response_model=list[ImportJobOut])
async def list_jobs(
    user: AuthenticatedUser = Depends(require_schulleitung),
    settings: Settings = Depends(get_settings),
    session: AsyncSession = Depends(get_session),
) -> list[ImportJobOut]:
    school_ids = None if user.is_admin else list(user.school_scope)
    svc = ImportService(session, settings, user.to_scope())
    jobs = await svc.list_jobs(school_ids=school_ids)
    return [ImportJobOut.model_validate(j) for j in jobs]


@router.post(
    "",
    response_model=ImportJobDetailOut,
    status_code=status.HTTP_201_CREATED,
)
async def stage_import(
    kind: str,
    file: UploadFile,
    request: Request,
    school_id: int | None = Query(default=None),
    user: AuthenticatedUser = Depends(require_schulleitung),
    settings: Settings = Depends(get_settings),
    session: AsyncSession = Depends(get_session),
) -> ImportJobDetailOut:
    if kind not in ALLOWED_IMPORT_KINDS:
        raise HTTPException(status_code=400, detail="unknown_kind")
    target_school = _resolve_school_id(school_id, user)

    raw = await file.read()
    try:
        csv_text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise HTTPException(status_code=400, detail="csv_not_utf8") from exc

    ip, request_id = _ip_request_id(request)
    svc = ImportService(session, settings, user.to_scope())
    try:
        summary = await svc.stage(
            school_id=target_school,
            kind=kind,
            csv_text=csv_text,
            filename=file.filename,
            ip=ip,
            request_id=request_id,
        )
    except InvalidCsvError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    job, rows, counts = await svc.get_with_rows(job_id=summary.job.id)
    return ImportJobDetailOut(
        id=job.id,
        school_id=job.school_id,
        kind=job.kind,
        status=job.status,
        filename=job.filename,
        created_by_upn=job.created_by_upn,
        created_at=job.created_at,
        applied_at=job.applied_at,
        summary=job.summary,
        rows=[ImportStagedRowOut.model_validate(r) for r in rows],
        counts=counts,
    )


@router.get("/{job_id}", response_model=ImportJobDetailOut)
async def get_job(
    job_id: int,
    user: AuthenticatedUser = Depends(require_schulleitung),
    settings: Settings = Depends(get_settings),
    session: AsyncSession = Depends(get_session),
) -> ImportJobDetailOut:
    svc = ImportService(session, settings, user.to_scope())
    try:
        job, rows, counts = await svc.get_with_rows(job_id=job_id)
    except ImportJobNotFoundError as exc:
        raise HTTPException(status_code=404, detail="import_job_not_found") from exc
    if not user.is_admin and job.school_id not in user.school_scope:
        raise HTTPException(status_code=404, detail="import_job_not_found")
    return ImportJobDetailOut(
        id=job.id,
        school_id=job.school_id,
        kind=job.kind,
        status=job.status,
        filename=job.filename,
        created_by_upn=job.created_by_upn,
        created_at=job.created_at,
        applied_at=job.applied_at,
        summary=job.summary,
        rows=[ImportStagedRowOut.model_validate(r) for r in rows],
        counts=counts,
    )


@router.post("/{job_id}/apply", response_model=ImportJobDetailOut)
async def apply_job(
    job_id: int,
    request: Request,
    user: AuthenticatedUser = Depends(require_schulleitung),
    settings: Settings = Depends(get_settings),
    session: AsyncSession = Depends(get_session),
) -> ImportJobDetailOut:
    svc = ImportService(session, settings, user.to_scope())
    try:
        job_pre, _, _ = await svc.get_with_rows(job_id=job_id)
    except ImportJobNotFoundError as exc:
        raise HTTPException(status_code=404, detail="import_job_not_found") from exc
    if not user.is_admin and job_pre.school_id not in user.school_scope:
        raise HTTPException(status_code=404, detail="import_job_not_found")

    ip, request_id = _ip_request_id(request)
    try:
        await svc.apply(job_id=job_id, ip=ip, request_id=request_id)
    except ImportJobBadStateError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    job, rows, counts = await svc.get_with_rows(job_id=job_id)
    return ImportJobDetailOut(
        id=job.id,
        school_id=job.school_id,
        kind=job.kind,
        status=job.status,
        filename=job.filename,
        created_by_upn=job.created_by_upn,
        created_at=job.created_at,
        applied_at=job.applied_at,
        summary=job.summary,
        rows=[ImportStagedRowOut.model_validate(r) for r in rows],
        counts=counts,
    )


@router.delete("/{job_id}", status_code=status.HTTP_204_NO_CONTENT)
async def cancel_job(
    job_id: int,
    request: Request,
    user: AuthenticatedUser = Depends(require_schulleitung),
    settings: Settings = Depends(get_settings),
    session: AsyncSession = Depends(get_session),
) -> None:
    svc = ImportService(session, settings, user.to_scope())
    try:
        job_pre, _, _ = await svc.get_with_rows(job_id=job_id)
    except ImportJobNotFoundError as exc:
        raise HTTPException(status_code=404, detail="import_job_not_found") from exc
    if not user.is_admin and job_pre.school_id not in user.school_scope:
        raise HTTPException(status_code=404, detail="import_job_not_found")

    ip, request_id = _ip_request_id(request)
    try:
        await svc.cancel(job_id=job_id, ip=ip, request_id=request_id)
    except ImportJobBadStateError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return None


__all__ = ["router"]
