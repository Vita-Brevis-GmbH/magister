"""Admin-only ``/admin/modules`` — read + configure the M6 feature modules.

The instance profile (school/company/neutral) seeds the default module set +
vocabulary; per-module overrides are the source of truth and win over the
profile default (ADR-0008, Phase 1). The non-toggleable ``platform`` base can
never be disabled.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from magister_api.auth.current_user import AuthenticatedUser
from magister_api.auth.rbac import require_admin
from magister_api.config import Settings, get_settings
from magister_api.db import get_session
from magister_api.modules import catalog
from magister_api.routers._helpers import _ip_request_id
from magister_api.schemas.modules import AdminModuleOut, AdminModulesOut, ModuleSettingsUpdate
from magister_api.services.app_settings import AppSettingsService

router = APIRouter(prefix="/admin/modules", tags=["admin"])


def _view(profile: str, overrides: dict[str, bool]) -> AdminModulesOut:
    enabled = set(catalog.effective_enabled_ids(profile, overrides))
    return AdminModulesOut(
        instance_profile=profile,
        known_profiles=list(catalog.KNOWN_PROFILES),
        modules=[
            AdminModuleOut(
                id=m.id,
                toggleable=m.toggleable,
                enabled=m.id in enabled,
                depends_on=list(m.depends_on),
            )
            for m in catalog.MODULE_CATALOG
        ],
    )


@router.get("", response_model=AdminModulesOut)
async def get_modules(
    user: AuthenticatedUser = Depends(require_admin),
    settings: Settings = Depends(get_settings),
    session: AsyncSession = Depends(get_session),
) -> AdminModulesOut:
    cfg = await AppSettingsService(session, settings).get_module_settings()
    return _view(cfg.instance_profile, cfg.module_overrides)


@router.put("", response_model=AdminModulesOut)
async def put_modules(
    request: Request,
    payload: ModuleSettingsUpdate,
    user: AuthenticatedUser = Depends(require_admin),
    settings: Settings = Depends(get_settings),
    session: AsyncSession = Depends(get_session),
) -> AdminModulesOut:
    svc = AppSettingsService(session, settings)
    current = await svc.get_module_settings()

    profile = (
        payload.instance_profile
        if payload.instance_profile is not None
        else current.instance_profile
    )
    if profile not in catalog.KNOWN_PROFILES:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "unknown_profile")

    overrides = dict(current.module_overrides)
    if payload.module_overrides is not None:
        for mid, on in payload.module_overrides.items():
            meta = catalog.get_meta(mid)
            if meta is None:
                raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"unknown_module:{mid}")
            if not meta.toggleable:
                raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"not_toggleable:{mid}")
            overrides[mid] = on

    enabled = set(catalog.effective_enabled_ids(profile, overrides))
    violations = catalog.dependency_violations(enabled)
    if violations:
        mod, dep = violations[0]
        raise HTTPException(status.HTTP_409_CONFLICT, f"dependency:{mod}_needs_{dep}")

    ip, request_id = _ip_request_id(request)
    updated = await svc.set_module_settings(
        instance_profile=payload.instance_profile,
        module_overrides=overrides if payload.module_overrides is not None else None,
        actor_upn=user.upn,
        actor_object_guid=user.ad_object_guid,
        ip=ip,
        request_id=request_id,
    )
    return _view(updated.instance_profile, updated.module_overrides)


__all__ = ["router"]
