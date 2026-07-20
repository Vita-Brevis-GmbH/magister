"""``/classes`` CRUD router. Schulleitung-or-Admin only.

- POST /classes — create (Schulleitung writes into their own school; Admin must pass ``school_id``)
- GET /classes — list active classes within scope
- GET /classes/{id} — single class within scope
- PATCH /classes/{id} — rename (name and/or kuerzel)
- DELETE /classes/{id} — soft-delete via status='archived'
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from magister_api.ad.client import AdClient
from magister_api.auth.class_perm import require_class_writer
from magister_api.auth.current_user import AuthenticatedUser
from magister_api.auth.rbac import require_schulleitung
from magister_api.config import Settings, get_settings
from magister_api.db import get_session
from magister_api.repositories.class_memberships import ClassMembershipRepository
from magister_api.repositories.class_teachers import ClassTeacherRoleRepository
from magister_api.repositories.devices import DeviceRepository
from magister_api.routers._helpers import _ip_request_id
from magister_api.routers.admin_sync import get_ad_client
from magister_api.schemas.classes import (
    ClassAdvanceRequest,
    ClassCreate,
    ClassDeviceOut,
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
from magister_api.services.devices import DeviceService

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
    ad: AdClient = Depends(get_ad_client),
) -> ClassPromotionResult:
    """Move all active students from this class to ``target_class_id``.

    Optionally archives the source class afterwards. Each student is attempted
    atomically; overlap failures are reported in ``errors`` while the rest are
    committed. Students whose grade crosses a Zyklus get their AD groups
    re-assigned to the new Zyklus template.
    """
    if payload.target_class_id == class_id:
        raise HTTPException(status_code=422, detail="source_and_target_must_differ")

    svc = ClassService(session, settings, user.to_scope(), ad_client=ad)
    ip, request_id = _ip_request_id(request)
    try:
        result = await svc.promote(
            source_class_id=class_id,
            target_class_id=payload.target_class_id,
            archive_source=payload.archive_source,
            student_guids=payload.student_guids,
            grade_overrides=payload.grade_overrides,
            bump_grade=payload.bump_grade,
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


@router.post("/{class_id}/advance", response_model=ClassPromotionResult)
async def advance_class_students(
    class_id: int,
    payload: ClassAdvanceRequest,
    request: Request,
    user: AuthenticatedUser = Depends(require_schulleitung),
    settings: Settings = Depends(get_settings),
    session: AsyncSession = Depends(get_session),
    ad: AdClient = Depends(get_ad_client),
) -> ClassPromotionResult:
    """Move and/or re-grade the selected students of this class.

    Drives the class-detail multi-select actions: move to another class (any
    direction) and/or raise the school year — including keeping the same class
    and only advancing the grade (``target_class_id`` omitted). Students whose
    grade crosses a Zyklus get their AD groups re-assigned accordingly.
    """
    svc = ClassService(session, settings, user.to_scope(), ad_client=ad)
    ip, request_id = _ip_request_id(request)
    try:
        result = await svc.advance_students(
            source_class_id=class_id,
            student_guids=payload.student_guids,
            grade_delta=payload.grade_delta,
            target_class_id=payload.target_class_id,
            archive_source=payload.archive_source,
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


@router.get("/{class_id}/devices", response_model=list[ClassDeviceOut])
async def list_class_devices(
    class_id: int,
    user: AuthenticatedUser = Depends(require_class_writer),
    settings: Settings = Depends(get_settings),
    session: AsyncSession = Depends(get_session),
) -> list[ClassDeviceOut]:
    """Devices tied to this class: assigned to the class itself, to one of its
    students, or to one of its teachers — each with a friendly "assigned to
    whom" label. ``require_class_writer`` already authorizes the caller for this
    class, so the device scope filter is deliberately bypassed here."""
    scope = user.to_scope()
    students = await ClassMembershipRepository(session).list_for_class(class_id, only_active=True)
    teachers = await ClassTeacherRoleRepository(session).list_active_for_class(class_id)
    student_guids = {m.ad_object_guid for m in students}
    teacher_guids = {t.ad_object_guid for t in teachers}

    devices = await DeviceRepository(session, scope).list_for_class_context(
        class_id, student_guids | teacher_guids
    )
    if not devices:
        return []

    person_guids = {d.assigned_person_guid for d in devices if d.assigned_person_guid}
    names = await DeviceService(session, settings, scope).person_names(person_guids)
    cls = await ClassService(session, settings, scope).get(class_id)

    out: list[ClassDeviceOut] = []
    for d in devices:
        guid = d.assigned_person_guid
        if guid and guid in teacher_guids:
            kind: str = "teacher"
            label = names.get(guid, guid)
        elif guid and guid in student_guids:
            kind = "student"
            label = names.get(guid, guid)
        else:
            kind = "class"
            label = cls.name
        out.append(
            ClassDeviceOut(
                id=d.id,
                name=d.name,
                device_type=d.device_type,
                serial_number=d.serial_number,
                is_loan=d.is_loan,
                assignee_kind=kind,  # type: ignore[arg-type]
                assignee_label=label,
            )
        )
    return out


@router.get("/{class_id}/password-list")
async def class_password_list(
    class_id: int,
    user: AuthenticatedUser = Depends(require_class_writer),
    settings: Settings = Depends(get_settings),
    session: AsyncSession = Depends(get_session),
    lang: str = Query(default="de", max_length=5),
) -> Response:
    """Confidential PDF of the class's students + their stored passwords.

    Admin / Schulleitung / KL of the class. Shows the vault password where one
    is stored (see the per-user "Passwort speichern" option), otherwise a
    placeholder.
    """
    from magister_api.services.class_password_list import (
        ClassNotFoundError as PwListClassNotFound,
    )
    from magister_api.services.class_password_list import ClassPasswordListService

    svc = ClassPasswordListService(session, settings, user.to_scope())
    try:
        pdf, filename = await svc.render(
            class_id=class_id,
            language=lang,
            generated_on=datetime.now(UTC).strftime("%d.%m.%Y"),
        )
    except PwListClassNotFound as exc:
        raise HTTPException(status_code=404, detail="class_not_found") from exc
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


__all__ = ["router"]
