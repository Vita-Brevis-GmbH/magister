"""``/classes`` CRUD router. Schulleitung-or-Admin only.

- POST /classes — create (Schulleitung writes into their own school; Admin must pass ``school_id``)
- GET /classes — list active classes within scope
- GET /classes/{id} — single class within scope
- PATCH /classes/{id} — rename (name and/or kuerzel)
- DELETE /classes/{id} — soft-delete via status='archived'
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from magister_api.auth.current_user import AuthenticatedUser
from magister_api.auth.rbac import require_schulleitung
from magister_api.config import Settings, get_settings
from magister_api.db import get_session
from magister_api.routers._helpers import _ip_request_id
from magister_api.schemas.classes import (
    ClassCreate,
    ClassOut,
    ClassPromotionRequest,
    ClassPromotionResult,
    ClassUpdate,
)
from magister_api.schemas.classes import ClassPromotionError as ClassPromotionErrorSchema
from magister_api.services.classes import (
    ClassGradeRangeError,
    ClassNotFoundError,
    ClassPermissionError,
    ClassService,
)

router = APIRouter(prefix="/classes", tags=["classes"])


def _resolve_school_id(payload_school_id: int, user: AuthenticatedUser) -> int:
    """Schulleitung implicitly writes into their own (single) school; Admin must pass it."""
    if user.is_admin:
        if payload_school_id <= 0:
            raise HTTPException(status_code=400, detail="school_id_required_for_admin")
        return payload_school_id
    if len(user.school_scope) != 1:
        # Schulleitung pro Schule = exact one. Anything else is a config bug.
        raise HTTPException(status_code=400, detail="schulleitung_scope_must_be_exactly_one_school")
    derived = user.school_scope[0]
    if payload_school_id and payload_school_id != derived:
        raise HTTPException(status_code=403, detail="cross_school_write")
    return derived


@router.post("", response_model=ClassOut, status_code=status.HTTP_201_CREATED)
async def create_class(
    payload: ClassCreate,
    request: Request,
    user: AuthenticatedUser = Depends(require_schulleitung),
    settings: Settings = Depends(get_settings),
    session: AsyncSession = Depends(get_session),
) -> ClassOut:
    school_id = _resolve_school_id(payload.school_id, user)
    svc = ClassService(session, settings, user.to_scope())
    ip, request_id = _ip_request_id(request)
    try:
        row = await svc.create(
            school_id=school_id,
            name=payload.name,
            kuerzel=payload.kuerzel,
            jahrgangsstufe=payload.jahrgangsstufe,
            jahrgangsstufe_bis=payload.jahrgangsstufe_bis,
            details=payload.details,
            ip=ip,
            request_id=request_id,
        )
    except ClassPermissionError as exc:
        raise HTTPException(status_code=403, detail="cross_school_write") from exc
    return ClassOut.model_validate(row)


@router.get("", response_model=list[ClassOut])
async def list_classes(
    user: AuthenticatedUser = Depends(require_schulleitung),
    settings: Settings = Depends(get_settings),
    session: AsyncSession = Depends(get_session),
) -> list[ClassOut]:
    svc = ClassService(session, settings, user.to_scope())
    rows = await svc.list_active()
    return [ClassOut.model_validate(r) for r in rows]


@router.get("/{class_id}", response_model=ClassOut)
async def get_class(
    class_id: int,
    user: AuthenticatedUser = Depends(require_schulleitung),
    settings: Settings = Depends(get_settings),
    session: AsyncSession = Depends(get_session),
) -> ClassOut:
    svc = ClassService(session, settings, user.to_scope())
    try:
        row = await svc.get(class_id)
    except ClassNotFoundError as exc:
        raise HTTPException(status_code=404, detail="class_not_found") from exc
    return ClassOut.model_validate(row)


@router.patch("/{class_id}", response_model=ClassOut)
async def patch_class(
    class_id: int,
    payload: ClassUpdate,
    request: Request,
    user: AuthenticatedUser = Depends(require_schulleitung),
    settings: Settings = Depends(get_settings),
    session: AsyncSession = Depends(get_session),
) -> ClassOut:
    svc = ClassService(session, settings, user.to_scope())
    ip, request_id = _ip_request_id(request)
    try:
        row = await svc.rename(
            class_id=class_id,
            new_name=payload.name,
            new_kuerzel=payload.kuerzel,
            new_details=payload.details,
            new_jahrgangsstufe=payload.jahrgangsstufe,
            set_jahrgangsstufe_bis="jahrgangsstufe_bis" in payload.model_fields_set,
            new_jahrgangsstufe_bis=payload.jahrgangsstufe_bis,
            ip=ip,
            request_id=request_id,
        )
    except ClassNotFoundError as exc:
        raise HTTPException(status_code=404, detail="class_not_found") from exc
    except ClassGradeRangeError as exc:
        raise HTTPException(status_code=422, detail="invalid_grade_range") from exc
    return ClassOut.model_validate(row)


@router.delete("/{class_id}", status_code=status.HTTP_204_NO_CONTENT)
async def archive_class(
    class_id: int,
    request: Request,
    user: AuthenticatedUser = Depends(require_schulleitung),
    settings: Settings = Depends(get_settings),
    session: AsyncSession = Depends(get_session),
) -> None:
    svc = ClassService(session, settings, user.to_scope())
    ip, request_id = _ip_request_id(request)
    try:
        await svc.archive(class_id=class_id, ip=ip, request_id=request_id)
    except ClassNotFoundError as exc:
        raise HTTPException(status_code=404, detail="class_not_found") from exc
    return None


@router.post("/{class_id}/promote", response_model=ClassPromotionResult)
async def promote_class(
    class_id: int,
    payload: ClassPromotionRequest,
    request: Request,
    user: AuthenticatedUser = Depends(require_schulleitung),
    settings: Settings = Depends(get_settings),
    session: AsyncSession = Depends(get_session),
) -> ClassPromotionResult:
    """Move all active students from this class to ``target_class_id``.

    Optionally archives the source class afterwards. Each student is attempted
    atomically; overlap failures are reported in ``errors`` while the rest are
    committed.
    """
    if payload.target_class_id == class_id:
        raise HTTPException(status_code=422, detail="source_and_target_must_differ")

    svc = ClassService(session, settings, user.to_scope())
    ip, request_id = _ip_request_id(request)
    try:
        result = await svc.promote(
            source_class_id=class_id,
            target_class_id=payload.target_class_id,
            archive_source=payload.archive_source,
            student_guids=payload.student_guids,
            ip=ip,
            request_id=request_id,
        )
    except ClassNotFoundError as exc:
        raise HTTPException(status_code=404, detail="class_not_found") from exc

    return ClassPromotionResult(
        students_moved=result.students_moved,
        students_failed=result.students_failed,
        errors=[ClassPromotionErrorSchema(ad_object_guid=g, detail=d) for g, d in result.errors],
        source_archived=result.source_archived,
    )


__all__ = ["router"]
