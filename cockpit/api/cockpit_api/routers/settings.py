"""Systemeinstellungen und Rechte-Matrix als Soll-Zustand (ADR-0017).

Drei Flächen:

* `/api/platform/settings` — die Vorgaben für alle Kunden.
* `/api/tenants/{id}/settings` — die Abweichungen eines Kunden.
* `/api/tenants/{id}/desired-state` — was daraus folgt. Das ist die Fläche,
  die die **Datenebene** abholt; sie schreibt nichts und liest nur.

Die Prüfungen sitzen im Dienst (`services/settings.py`), damit sie auch für
einen CLI-Aufruf gelten. Dieses Modul übersetzt sie in HTTP: ein verbotener
oder unbekannter Schlüssel ist **422** — die Anfrage ist syntaktisch richtig
und inhaltlich nicht erlaubt.
"""

from __future__ import annotations

import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from cockpit_api.auth import require_bootstrap_token
from cockpit_api.db import get_session
from cockpit_api.models import Tenant
from cockpit_api.models.settings import TenantSettings
from cockpit_api.schemas.settings import (
    DesiredStateOut,
    PlatformSettingsOut,
    PlatformSettingsUpdate,
    TenantSettingsOut,
    TenantSettingsUpdate,
)
from cockpit_api.services.settings import SettingsError, SettingsService

logger = logging.getLogger(__name__)

platform = APIRouter(
    prefix="/platform", tags=["settings"], dependencies=[Depends(require_bootstrap_token)]
)
tenant_scoped = APIRouter(
    prefix="/tenants/{tenant_id}",
    tags=["settings"],
    dependencies=[Depends(require_bootstrap_token)],
)


async def _known_tenant(session: AsyncSession, tenant_id: UUID) -> Tenant:
    tenant = await session.get(Tenant, tenant_id)
    if tenant is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "unknown tenant")
    return tenant


def _tenant_out(row: TenantSettings | None, tenant_id: UUID) -> TenantSettingsOut:
    """Auch der leere Fall ist eine Antwort.

    Kein Eintrag heisst „keine Abweichung" — und nicht 404. Ein 404 zwänge
    jede Oberfläche zu einer Sonderbehandlung für den Normalfall.
    """
    if row is None:
        return TenantSettingsOut(
            tenant_id=str(tenant_id),
            overrides={},
            rbac=None,
            updated_at=None,
            updated_by=None,
        )
    return TenantSettingsOut(
        tenant_id=str(row.tenant_id),
        overrides=row.overrides,
        rbac=row.rbac,
        updated_at=row.updated_at,
        updated_by=row.updated_by,
    )


@platform.get("/settings", response_model=PlatformSettingsOut)
async def get_platform_settings(
    session: AsyncSession = Depends(get_session),
) -> PlatformSettingsOut:
    row = await SettingsService(session).platform()
    await session.commit()
    return PlatformSettingsOut.model_validate(row)


@platform.put("/settings", response_model=PlatformSettingsOut)
async def put_platform_settings(
    body: PlatformSettingsUpdate,
    session: AsyncSession = Depends(get_session),
) -> PlatformSettingsOut:
    svc = SettingsService(session)
    try:
        row = await svc.set_platform(defaults=body.defaults, rbac=body.rbac, actor=body.actor)
    except SettingsError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    await session.commit()
    logger.info("Plattform-Vorgaben geändert von %s", body.actor)
    return PlatformSettingsOut.model_validate(row)


@tenant_scoped.get("/settings", response_model=TenantSettingsOut)
async def get_tenant_settings(
    tenant_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> TenantSettingsOut:
    await _known_tenant(session, tenant_id)
    row = await SettingsService(session).tenant(tenant_id)
    return _tenant_out(row, tenant_id)


@tenant_scoped.put("/settings", response_model=TenantSettingsOut)
async def put_tenant_settings(
    tenant_id: UUID,
    body: TenantSettingsUpdate,
    session: AsyncSession = Depends(get_session),
) -> TenantSettingsOut:
    tenant = await _known_tenant(session, tenant_id)
    svc = SettingsService(session)
    try:
        row = await svc.set_tenant(
            tenant_id,
            overrides=body.overrides,
            rbac=body.rbac,
            clear_rbac=body.clear_rbac,
            actor=body.actor,
        )
    except SettingsError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    await session.commit()
    # Der Name des Kunden im Protokoll, nicht nur die Id: wer den Log liest,
    # soll nicht erst eine Tabelle befragen müssen.
    logger.info("Einstellungen von %s geändert von %s", tenant.slug, body.actor)
    return _tenant_out(row, tenant_id)


@tenant_scoped.get("/desired-state", response_model=DesiredStateOut)
async def get_desired_state(
    tenant_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> DesiredStateOut:
    """Der Soll-Zustand, wie die Datenebene ihn abholt (ADR-0017 D3).

    Nur lesend. Die Konsole schreibt nicht in das Schema des Kunden — sie hat
    dorthin keinen Zugang, und das ist keine Auslassung.
    """
    tenant = await _known_tenant(session, tenant_id)
    state = await SettingsService(session).desired_state(tenant)
    await session.commit()
    return DesiredStateOut(**state)


__all__ = ["platform", "tenant_scoped"]
