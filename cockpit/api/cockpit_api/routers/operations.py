"""Betrieb eines Kunden aus der Konsole (ADR-0024).

Drei Flächen je Kunde:

* ``/status`` — die Zustandsmeldung der Datenebene annehmen (POST, Dienst)
  und anzeigen (GET). Der zweite Rückkanal neben der Schemastand-Meldung.
* ``/sealed-secrets`` — ein Geheimnis versiegeln und als Chiffrat ablegen.
* ``/maintenance`` — Wartungsaufträge erfassen; ausgeführt werden sie von der
  Datenebene, die sie mit dem Soll-Zustand abholt.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from cockpit_api.auth import Caller, require_identity, require_person
from cockpit_api.db import get_session
from cockpit_api.models import Tenant
from cockpit_api.models.operations import (
    MaintenanceState,
    TenantMaintenanceRequest,
    TenantSealedSecret,
    TenantStatusReport,
)
from cockpit_api.schemas.operations import (
    MaintenanceRequestIn,
    MaintenanceRequestOut,
    SealedSecretIn,
    SealedSecretOut,
    StatusOut,
    StatusReport,
)
from cockpit_api.services.sealing import SEALABLE, SealingError, key_id, seal

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/tenants/{tenant_id}",
    tags=["operations"],
    dependencies=[Depends(require_identity)],
)


async def _tenant(session: AsyncSession, tenant_id: UUID) -> Tenant:
    tenant = await session.get(Tenant, tenant_id)
    if tenant is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "unknown tenant")
    return tenant


async def _report(session: AsyncSession, tenant_id: UUID) -> TenantStatusReport | None:
    return await session.get(TenantStatusReport, tenant_id)


# --- Zustand ---------------------------------------------------------------


@router.post("/status", status_code=status.HTTP_204_NO_CONTENT)
async def accept_status(
    tenant_id: UUID,
    body: StatusReport,
    session: AsyncSession = Depends(get_session),
) -> None:
    """Die Zustandsmeldung der Datenebene annehmen (ADR-0024 D1).

    Kein ``require_person``: es meldet ein Dienst. Was ankommt, ist geprüft
    (``extra=forbid``, begrenzte Längen) und enthält keine Personendaten.
    Wartungsergebnisse in der Meldung schliessen die zugehörigen Aufträge ab.
    """
    tenant = await _tenant(session, tenant_id)
    row = await _report(session, tenant_id)
    payload = body.model_dump(mode="json")
    if row is None:
        session.add(TenantStatusReport(tenant_id=tenant.id, payload=payload))
    else:
        row.payload = payload
        row.reported_at = datetime.now(UTC)

    for item in body.maintenance:
        request = await session.get(TenantMaintenanceRequest, item.id)
        if request is None or request.tenant_id != tenant.id:
            continue
        if request.state is not MaintenanceState.requested:
            continue
        request.state = MaintenanceState.done if item.ok else MaintenanceState.failed
        request.finished_at = datetime.now(UTC)
        request.result = dict(item.result)
        logger.info("Wartungsauftrag %s für %s: %s", request.id, tenant.slug, request.state.value)
    await session.commit()


@router.get("/status", response_model=StatusOut)
async def get_status(tenant_id: UUID, session: AsyncSession = Depends(get_session)) -> StatusOut:
    tenant = await _tenant(session, tenant_id)
    row = await _report(session, tenant_id)
    report = StatusReport.model_validate(row.payload) if row else None
    profile = str(tenant.profile)
    matches = None
    if report is not None and report.effective_profile is not None:
        matches = report.effective_profile == profile
    return StatusOut(
        reported_at=row.reported_at if row else None,
        report=report,
        console_profile=profile,
        profile_matches=matches,
    )


# --- Versiegelte Geheimnisse ------------------------------------------------


async def _sealed_view(session: AsyncSession, tenant_id: UUID) -> list[SealedSecretOut]:
    row = await _report(session, tenant_id)
    report = StatusReport.model_validate(row.payload) if row else None
    stored = {
        s.name: s
        for s in (
            await session.execute(
                select(TenantSealedSecret).where(TenantSealedSecret.tenant_id == tenant_id)
            )
        ).scalars()
    }
    out: list[SealedSecretOut] = []
    for name in sorted(SEALABLE):
        item = stored.get(name)
        current = report.sealed_key_id if report else None
        out.append(
            SealedSecretOut(
                name=name,
                sealed=item is not None,
                key_current=(item.key_id == current) if (item and current) else None,
                present_in_tenant=report.secrets_present.get(name) if report else None,
                updated_at=item.updated_at if item else None,
                updated_by=item.updated_by if item else None,
            )
        )
    return out


@router.get("/sealed-secrets", response_model=list[SealedSecretOut])
async def list_sealed(
    tenant_id: UUID, session: AsyncSession = Depends(get_session)
) -> list[SealedSecretOut]:
    await _tenant(session, tenant_id)
    return await _sealed_view(session, tenant_id)


@router.put("/sealed-secrets/{name}", response_model=list[SealedSecretOut])
async def put_sealed(
    tenant_id: UUID,
    name: str,
    body: SealedSecretIn,
    caller: Caller = Depends(require_person),
    session: AsyncSession = Depends(get_session),
) -> list[SealedSecretOut]:
    """Ein Geheimnis versiegeln (ADR-0024 D3).

    Der Klartext lebt nur in dieser Anfrage: er wird mit dem öffentlichen
    Schlüssel versiegelt, den die Datenebene dieses Kunden gemeldet hat, und
    nicht gespeichert, nicht protokolliert, nicht zurückgegeben.
    """
    tenant = await _tenant(session, tenant_id)
    if name not in SEALABLE:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"'{name}' ist kein versiegelbares Geheimnis. Erlaubt: {', '.join(sorted(SEALABLE))}.",
        )
    row = await _report(session, tenant_id)
    report = StatusReport.model_validate(row.payload) if row else None
    if report is None or not report.sealed_public_key:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Die Installation dieses Kunden hat noch keinen Schlüssel gemeldet. Erst wenn sie "
            "sich meldet (Reiter Übersicht → Zustand), lässt sich ein Geheimnis versiegeln.",
        )
    try:
        ciphertext = seal(
            report.sealed_public_key, body.value, tenant_ref=str(tenant.id), name=name
        )
    except SealingError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    stored = await session.get(TenantSealedSecret, (tenant.id, name))
    if stored is None:
        session.add(
            TenantSealedSecret(
                tenant_id=tenant.id,
                name=name,
                ciphertext=ciphertext,
                key_id=key_id(report.sealed_public_key),
                updated_by=caller.actor,
            )
        )
    else:
        stored.ciphertext = ciphertext
        stored.key_id = key_id(report.sealed_public_key)
        stored.updated_by = caller.actor
        stored.updated_at = datetime.now(UTC)
    await session.commit()
    logger.info("Geheimnis %s für %s versiegelt von %s", name, tenant.slug, caller.actor)
    return await _sealed_view(session, tenant_id)


# --- Wartungsaufträge -------------------------------------------------------


@router.get("/maintenance", response_model=list[MaintenanceRequestOut])
async def list_maintenance(
    tenant_id: UUID, session: AsyncSession = Depends(get_session)
) -> list[TenantMaintenanceRequest]:
    await _tenant(session, tenant_id)
    stmt = (
        select(TenantMaintenanceRequest)
        .where(TenantMaintenanceRequest.tenant_id == tenant_id)
        .order_by(TenantMaintenanceRequest.requested_at.desc())
        .limit(50)
    )
    return list((await session.execute(stmt)).scalars())


@router.post(
    "/maintenance", response_model=MaintenanceRequestOut, status_code=status.HTTP_201_CREATED
)
async def request_maintenance(
    tenant_id: UUID,
    body: MaintenanceRequestIn,
    caller: Caller = Depends(require_person),
    session: AsyncSession = Depends(get_session),
) -> TenantMaintenanceRequest:
    """Einen Wartungsauftrag erfassen (ADR-0024 D4).

    Ausgeführt wird er beim nächsten Abgleich der Datenebene — im Protokoll
    des Kunden steht dann, wer bei Vita Brevis ihn ausgelöst hat und warum.
    Ein zweiter offener Auftrag derselben Art ist nicht möglich.
    """
    tenant = await _tenant(session, tenant_id)
    if body.confirm_slug.strip() != tenant.slug:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"Zur Bestätigung den Kürzel dieses Kunden eintippen ({tenant.slug}).",
        )
    open_same = (
        await session.execute(
            select(TenantMaintenanceRequest.id)
            .where(TenantMaintenanceRequest.tenant_id == tenant.id)
            .where(TenantMaintenanceRequest.action == body.action)
            .where(TenantMaintenanceRequest.state == MaintenanceState.requested)
        )
    ).first()
    if open_same is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Ein Auftrag dieser Art ist für diesen Kunden schon offen."
        )
    row = TenantMaintenanceRequest(
        tenant_id=tenant.id,
        action=body.action,
        reason=body.reason.strip(),
        requested_by=caller.actor,
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)
    logger.info(
        "Wartungsauftrag %s (%s) für %s erfasst von %s",
        row.id,
        row.action.value,
        tenant.slug,
        caller.actor,
    )
    return row


@router.post("/maintenance/{request_id}/cancel", response_model=MaintenanceRequestOut)
async def cancel_maintenance(
    tenant_id: UUID,
    request_id: UUID,
    caller: Caller = Depends(require_person),
    session: AsyncSession = Depends(get_session),
) -> TenantMaintenanceRequest:
    row = await session.get(TenantMaintenanceRequest, request_id)
    if row is None or row.tenant_id != tenant_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "unknown maintenance request")
    if row.state is not MaintenanceState.requested:
        raise HTTPException(status.HTTP_409_CONFLICT, f"Der Auftrag ist {row.state.value}.")
    row.state = MaintenanceState.cancelled
    row.finished_at = datetime.now(UTC)
    await session.commit()
    await session.refresh(row)
    logger.info("Wartungsauftrag %s zurückgezogen von %s", row.id, caller.actor)
    return row


__all__ = ["router"]
