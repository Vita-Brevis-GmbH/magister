"""Admin-only ``/templates`` — edit letter/mail (Vorlagen) templates.

Operators override the built-in Jinja letter templates with their own HTML +
subject per ``(key, language, school)``. Rendering is sandboxed; when no active
override exists the built-in template is used (M6 Feature B, ADR-0009 D2).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from magister_api.auth.current_user import AuthenticatedUser
from magister_api.auth.rbac import require_admin
from magister_api.config import Settings, get_settings
from magister_api.db import get_session
from magister_api.routers._helpers import _ip_request_id
from magister_api.schemas.document_templates import (
    DocumentTemplateListOut,
    DocumentTemplateMetaOut,
    DocumentTemplateOut,
    DocumentTemplatePreviewOut,
    DocumentTemplatePreviewRequest,
    DocumentTemplateSave,
    DocumentTemplateStarter,
)
from magister_api.services.app_settings import AppSettingsService
from magister_api.services.document_templates import (
    EDITABLE_KEYS,
    PLACEHOLDERS,
    DocumentTemplateService,
    TemplateRenderError,
    UnknownTemplateKeyError,
    sample_context,
    starters_for_profile,
)

router = APIRouter(prefix="/templates", tags=["templates"])

_LANGUAGES = ("de", "fr", "it", "en")


def _meta(profile: str) -> DocumentTemplateMetaOut:
    return DocumentTemplateMetaOut(
        keys=list(EDITABLE_KEYS),
        placeholders=list(PLACEHOLDERS),
        languages=list(_LANGUAGES),
        starters={
            key: DocumentTemplateStarter(subject=s["subject"], body_html=s["body_html"])
            for key, s in starters_for_profile(profile).items()
        },
    )


@router.get("", response_model=DocumentTemplateListOut)
async def list_templates(
    school_id: int | None = None,
    user: AuthenticatedUser = Depends(require_admin),  # noqa: ARG001
    settings: Settings = Depends(get_settings),
    session: AsyncSession = Depends(get_session),
) -> DocumentTemplateListOut:
    svc = DocumentTemplateService(session, settings)
    rows = await svc.list_for_admin(school_id=school_id)
    cfg = await AppSettingsService(session, settings).get_module_settings()
    return DocumentTemplateListOut(
        templates=[DocumentTemplateOut.model_validate(r) for r in rows],
        meta=_meta(cfg.instance_profile),
    )


@router.put("", response_model=DocumentTemplateOut)
async def save_template(
    request: Request,
    payload: DocumentTemplateSave,
    user: AuthenticatedUser = Depends(require_admin),
    settings: Settings = Depends(get_settings),
    session: AsyncSession = Depends(get_session),
) -> DocumentTemplateOut:
    svc = DocumentTemplateService(session, settings)
    ip, request_id = _ip_request_id(request)
    try:
        row = await svc.save(
            key=payload.key,
            language=payload.language,
            school_id=payload.school_id,
            subject=payload.subject,
            body_html=payload.body_html,
            is_active=payload.is_active,
            actor_upn=user.upn,
            actor_object_guid=user.ad_object_guid,
            ip=ip,
            request_id=request_id,
        )
    except UnknownTemplateKeyError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"unknown_key:{exc}") from exc
    except TemplateRenderError as exc:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, f"template_invalid:{exc}"
        ) from exc
    return DocumentTemplateOut.model_validate(row)


@router.post("/preview", response_model=DocumentTemplatePreviewOut)
async def preview_template(
    payload: DocumentTemplatePreviewRequest,
    user: AuthenticatedUser = Depends(require_admin),  # noqa: ARG001
) -> DocumentTemplatePreviewOut:
    ctx = sample_context()
    try:
        html = DocumentTemplateService.render_body(payload.body_html, ctx)
        subject = (
            DocumentTemplateService.render_body(payload.subject, ctx) if payload.subject else None
        )
    except TemplateRenderError as exc:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, f"template_invalid:{exc}"
        ) from exc
    return DocumentTemplatePreviewOut(subject=subject, html=html)


@router.delete("/{template_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_template(
    template_id: int,
    request: Request,
    user: AuthenticatedUser = Depends(require_admin),
    settings: Settings = Depends(get_settings),
    session: AsyncSession = Depends(get_session),
) -> Response:
    svc = DocumentTemplateService(session, settings)
    ip, request_id = _ip_request_id(request)
    removed = await svc.delete(
        template_id=template_id,
        actor_upn=user.upn,
        actor_object_guid=user.ad_object_guid,
        ip=ip,
        request_id=request_id,
    )
    if not removed:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "template_not_found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


__all__ = ["router"]
