"""``/admin/group-templates`` — AD group templates (Zielrollen) CRUD.

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

from magister_api.auth.current_user import AuthenticatedUser
from magister_api.auth.rbac import require_manage
from magister_api.config import Settings, get_settings
from magister_api.db import get_session
from magister_api.models.group_template import GroupTemplate
from magister_api.routers._helpers import _ip_request_id
from magister_api.schemas.group_templates import (
    GroupTemplateCreate,
    GroupTemplateOut,
    GroupTemplateUpdate,
)
from magister_api.services.group_templates import (
    GroupTemplateNotFoundError,
    GroupTemplateService,
)

router = APIRouter(prefix="/admin/group-templates", tags=["admin"])


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
            ip=ip,
            request_id=request_id,
        )
    except GroupTemplateNotFoundError as exc:
        raise HTTPException(status_code=404, detail="group_template_not_found") from exc
    return _out(row, sids)


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
