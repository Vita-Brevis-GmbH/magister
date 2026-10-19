"""``/admin/group-templates`` — Zielgruppen CRUD (vormals Zielrollen).

A group template is a named, reusable bundle of AD group DNs, assignable to one
or more Standorte, chosen at "neuen Benutzer anlegen" (filtered by Standort).
AD-global config (not personenbezogen) → unscoped rows; managed by any
management tier (``require_manage``: Admin / Schulleitung / SMI), matching the
per-school provisioning config surface.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from magister_api.ad.client import AdClient
from magister_api.auth.current_user import AuthenticatedUser
from magister_api.auth.effective_settings import get_effective_settings
from magister_api.auth.rbac import require_admin, require_manage
from magister_api.config import Settings, get_settings
from magister_api.db import get_session
from magister_api.models.group_template import GroupTemplate
from magister_api.routers._helpers import _ip_request_id
from magister_api.routers.admin_sync import get_ad_client
from magister_api.schemas.group_templates import (
    AssignRequest,
    AssignResultOut,
    DefaultsRequest,
    GroupTemplateCreate,
    GroupTemplateOut,
    GroupTemplateUpdate,
)
from magister_api.services.group_templates import (
    GroupTemplateNotFoundError,
    GroupTemplateService,
    SchoolForDefaultsNotFoundError,
)
from magister_api.services.zielgruppen_assign import (
    ZielgruppenAssignService,
    ZielgruppeNotFoundError,
)

router = APIRouter(prefix="/admin/group-templates", tags=["admin"])


_OPTIONS = (
    "password_profile",
    "force_change",
    "cannot_change_password",
    "password_never_expires",
    "store_password",
)


def _options(payload: GroupTemplateCreate | GroupTemplateUpdate) -> dict[str, object]:
    return {k: getattr(payload, k) for k in _OPTIONS}


def _out(row: GroupTemplate, school_ids: list[int]) -> GroupTemplateOut:
    return GroupTemplateOut.model_validate(row).model_copy(update={"school_ids": school_ids})


@router.get("", response_model=list[GroupTemplateOut])
async def list_group_templates(
    school_id: int | None = None,
    user: AuthenticatedUser = Depends(require_manage),
    settings: Settings = Depends(get_settings),
    session: AsyncSession = Depends(get_session),
) -> list[GroupTemplateOut]:
    svc = GroupTemplateService(session, settings, user.to_scope())
    if school_id:
        rows, links = await svc.list_for_school(school_id)
    else:
        rows, links = await svc.list_all()
    return [_out(r, links.get(r.id, [])) for r in rows]


@router.post("", response_model=GroupTemplateOut, status_code=status.HTTP_201_CREATED)
async def create_group_template(
    payload: GroupTemplateCreate,
    request: Request,
    user: AuthenticatedUser = Depends(require_manage),
    settings: Settings = Depends(get_settings),
    session: AsyncSession = Depends(get_session),
) -> GroupTemplateOut:
    svc = GroupTemplateService(session, settings, user.to_scope())
    ip, request_id = _ip_request_id(request)
    row, sids = await svc.create(
        name=payload.name,
        description=payload.description,
        kind=payload.kind,
        ad_groups=payload.ad_groups,
        school_ids=payload.school_ids,
        options=_options(payload),
        ip=ip,
        request_id=request_id,
    )
    return _out(row, sids)


@router.patch("/{template_id}", response_model=GroupTemplateOut)
async def patch_group_template(
    template_id: int,
    payload: GroupTemplateUpdate,
    request: Request,
    user: AuthenticatedUser = Depends(require_manage),
    settings: Settings = Depends(get_settings),
    session: AsyncSession = Depends(get_session),
) -> GroupTemplateOut:
    svc = GroupTemplateService(session, settings, user.to_scope())
    ip, request_id = _ip_request_id(request)
    try:
        row, sids = await svc.update(
            template_id=template_id,
            name=payload.name,
            description=payload.description,
            kind=payload.kind,
            ad_groups=payload.ad_groups,
            school_ids=payload.school_ids,
            options=_options(payload),
            ip=ip,
            request_id=request_id,
        )
    except GroupTemplateNotFoundError as exc:
        raise HTTPException(status_code=404, detail="group_template_not_found") from exc
    return _out(row, sids)


@router.post("/defaults", response_model=list[GroupTemplateOut])
async def ensure_default_group_templates(
    payload: DefaultsRequest,
    request: Request,
    user: AuthenticatedUser = Depends(require_manage),
    settings: Settings = Depends(get_settings),
    session: AsyncSession = Depends(get_session),
) -> list[GroupTemplateOut]:
    """Fehlende Standard-Zielgruppen (Zyklus 1/2/3, Lehrperson) ergänzen.

    Gibt nur die neu angelegten zurück; eine leere Liste heisst: alles da.
    """
    svc = GroupTemplateService(session, settings, user.to_scope())
    ip, request_id = _ip_request_id(request)
    try:
        created = await svc.ensure_defaults(
            school_id=payload.school_id, ip=ip, request_id=request_id
        )
    except SchoolForDefaultsNotFoundError as exc:
        raise HTTPException(status_code=404, detail="school_not_found") from exc
    return [_out(r, [payload.school_id]) for r in created]


@router.post("/{template_id}/assign", response_model=list[AssignResultOut])
async def assign_group_template(
    template_id: int,
    payload: AssignRequest,
    request: Request,
    user: AuthenticatedUser = Depends(require_admin),
    settings: Settings = Depends(get_effective_settings),
    session: AsyncSession = Depends(get_session),
    ad: AdClient = Depends(get_ad_client),
) -> list[AssignResultOut]:
    """Bestehende Konten dieser Zielgruppe zuordnen.

    Gruppen der bisherigen Zielgruppe fallen weg, die der neuen kommen dazu;
    optional werden die Konto-Einstellungen übernommen. Admin-only wie das
    Anlegen, weil es AD-Gruppen schreibt. Ein Fehler bei einem Konto hält die
    anderen nicht auf — das Ergebnis nennt ihn je Konto.
    """
    svc = ZielgruppenAssignService(session, settings, user.to_scope(), ad)
    ip, request_id = _ip_request_id(request)
    try:
        results = await svc.assign(
            template_id=template_id,
            guids=payload.ad_object_guids,
            apply_settings=payload.apply_settings,
            ip=ip,
            request_id=request_id,
        )
    except ZielgruppeNotFoundError as exc:
        raise HTTPException(status_code=404, detail="group_template_not_found") from exc
    return [AssignResultOut(**vars(r)) for r in results]


@router.delete("/{template_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_group_template(
    template_id: int,
    request: Request,
    user: AuthenticatedUser = Depends(require_manage),
    settings: Settings = Depends(get_settings),
    session: AsyncSession = Depends(get_session),
) -> Response:
    svc = GroupTemplateService(session, settings, user.to_scope())
    ip, request_id = _ip_request_id(request)
    try:
        await svc.archive(template_id=template_id, ip=ip, request_id=request_id)
    except GroupTemplateNotFoundError as exc:
        raise HTTPException(status_code=404, detail="group_template_not_found") from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


__all__ = ["router"]
