"""Offboarding eines Kunden (ADR-0016 D8).

Fünf Endpunkte in einer festen Reihenfolge; die Schranken sitzen im Dienst
(``services/offboarding.py``) und nicht hier, damit sie auch für einen
CLI-Aufruf gelten. Dieses Modul übersetzt die Verstösse in HTTP: eine
Reihenfolgeverletzung ist **409 Conflict** und nicht 400 — die Anfrage ist
richtig geformt, nur zum falschen Zeitpunkt gestellt.

Der destruktive Schritt (``/drop``) verlangt zwei verschiedene Personen und
lässt sich nicht rückgängig machen. Der Schritt danach (``/key-destroyed``)
ist eine **Bestätigung durch einen Menschen** und keine Prüfung: der
Kundenschlüssel liegt in der Umgebung des Anwendungsservers, und dorthin
reicht die Konsole nicht.
"""

from __future__ import annotations

import logging
from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from cockpit_api.auth import require_bootstrap_token
from cockpit_api.config import settings
from cockpit_api.db import get_session
from cockpit_api.models import ExportJob, Tenant, TenantOffboarding
from cockpit_api.schemas.backup import (
    OffboardingAbort,
    OffboardingDrop,
    OffboardingKeyDestroyed,
    OffboardingOut,
    OffboardingStart,
)
from cockpit_api.services import offboarding as flow
from cockpit_api.services.backup import (
    OFFBOARDING_MARKER,
    BackupError,
    write_offboarding_marker,
)
from cockpit_api.services.provisioning import admin_engine

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/tenants/{tenant_id}/offboarding",
    tags=["offboarding"],
    dependencies=[Depends(require_bootstrap_token)],
)


async def _tenant(session: AsyncSession, tenant_id: UUID) -> Tenant:
    tenant = await session.get(Tenant, tenant_id)
    if tenant is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "unknown tenant")
    return tenant


async def _row(session: AsyncSession, tenant_id: UUID) -> TenantOffboarding:
    row = await session.get(TenantOffboarding, tenant_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "kein Offboarding erfasst")
    return row


def _conflict(exc: flow.OffboardingError) -> HTTPException:
    # 409 und nicht 400: die Anfrage ist richtig geformt, nur zum falschen
    # Zeitpunkt gestellt. Der Text nennt die Schranke — wer offboardet, soll
    # lesen können, *warum* jetzt nicht.
    return HTTPException(status.HTTP_409_CONFLICT, str(exc))


async def _serialized(session: AsyncSession, row: TenantOffboarding) -> OffboardingOut:
    """Erst festschreiben, dann abbilden.

    Vor dem Commit wäre ``updated_at`` noch ``None``, und nach einem UPDATE
    auf eine Spalte mit ``onupdate`` ist das Attribut abgelaufen — ein Zugriff
    darauf endet dann in ``MissingGreenlet``.
    """
    await session.commit()
    await session.refresh(row)
    return OffboardingOut.model_validate(row)


@router.get("", response_model=OffboardingOut)
async def get_offboarding(
    tenant_id: UUID, session: AsyncSession = Depends(get_session)
) -> OffboardingOut:
    await _tenant(session, tenant_id)
    return OffboardingOut.model_validate(await _row(session, tenant_id))


@router.post("", response_model=OffboardingOut, status_code=status.HTTP_201_CREATED)
async def start_offboarding(
    tenant_id: UUID,
    body: OffboardingStart,
    session: AsyncSession = Depends(get_session),
) -> OffboardingOut:
    """Kündigung erfassen. Der Kunde wird ab sofort nicht mehr bedient."""
    tenant = await _tenant(session, tenant_id)
    try:
        row = await flow.start(
            session,
            tenant,
            reason=body.reason,
            requested_by=body.requested_by,
            grace_days=body.grace_days,
        )
    except flow.OffboardingError as exc:
        raise _conflict(exc) from exc
    return await _serialized(session, row)


@router.post("/export/{export_id}", response_model=OffboardingOut)
async def record_export(
    tenant_id: UUID,
    export_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> OffboardingOut:
    """Den zugestellten Export vermerken — die Löschsperre hängt daran."""
    await _tenant(session, tenant_id)
    row = await _row(session, tenant_id)
    export = await session.get(ExportJob, export_id)
    if export is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "unknown export")
    try:
        row = await flow.record_export(session, row, export)
    except flow.OffboardingError as exc:
        raise _conflict(exc) from exc
    return await _serialized(session, row)


@router.post("/drop", response_model=OffboardingOut)
async def drop_data(
    tenant_id: UUID,
    body: OffboardingDrop,
    session: AsyncSession = Depends(get_session),
) -> OffboardingOut:
    """Schema und Datenbankrolle löschen. **Unwiderruflich.**

    Vier Schranken davor: zugestellter Export, abgelaufene Karenzzeit, zwei
    verschiedene Personen, Kunde im Offboarding. Danach prüft der Dienst
    nach, dass Schema und Rolle wirklich weg sind — ein Vermerk „gelöscht"
    ohne Nachprüfung wäre wertlos.
    """
    tenant = await _tenant(session, tenant_id)
    row = await _row(session, tenant_id)
    engine = admin_engine()
    try:
        row = await flow.drop_data(
            session,
            tenant,
            row,
            engine=engine,
            dropped_by=body.dropped_by,
            approved_by=body.approved_by,
        )
    except flow.OffboardingError as exc:
        raise _conflict(exc) from exc
    finally:
        await engine.dispose()
    return await _serialized(session, row)


@router.post("/key-destroyed", response_model=OffboardingOut)
async def confirm_key_destroyed(
    tenant_id: UUID,
    body: OffboardingKeyDestroyed,
    session: AsyncSession = Depends(get_session),
) -> OffboardingOut:
    """Vernichtung des Kundenschlüssels festhalten (Crypto-Shredding).

    **Festhalten, nicht prüfen.** Der Schlüssel steht in der Umgebung des
    Anwendungsservers als ``MAGISTER_TENANT_AUDIT_KEY_<REF>``; die Konsole
    kommt nicht dorthin. Wer hier bestätigt, bestätigt eine Handlung, die er
    selbst ausgeführt hat. Aus dem Zeitpunkt berechnet sich ``purge_due_at`` —
    das Datum, das dem Kunden als endgültige Löschung zugesagt wird.
    """
    tenant = await _tenant(session, tenant_id)
    row = await _row(session, tenant_id)
    retention = await flow.retention_days_for(session, tenant)
    try:
        row = await flow.confirm_key_destroyed(
            session, row, confirmed_by=body.confirmed_by, retention_days=retention
        )
    except flow.OffboardingError as exc:
        raise _conflict(exc) from exc

    # Dem Aufräumjob sagen, dass für diesen Kunden ab jetzt die kurze Frist
    # gilt — auch für die Monatskopien (E15). Ohne diesen Schritt wäre die
    # Löschzusage aus D8 unwahr: eine Monatskopie kann elf Monate alt sein und
    # läge an `purge_due_at` noch auf dem Share.
    #
    # Scheitert das Schreiben, wird der Vorgang NICHT zurückgenommen: der
    # Kundenschlüssel ist vernichtet, das ist der wesentliche Schritt und
    # unwiderruflich. Aber die Antwort sagt es, und die Meldung nennt den
    # Handgriff — sonst läuft eine Frist, die niemand einhält.
    warning: str | None = None
    if settings.backup_share_root and row.purge_due_at is not None:
        try:
            write_offboarding_marker(
                Path(settings.backup_share_root),
                tenant.slug,
                purge_due_at=row.purge_due_at,
                key_id=row.key_id,
            )
        except (BackupError, OSError) as exc:
            warning = (
                f"Die Offboarding-Markierung auf dem Share liess sich nicht "
                f"schreiben ({exc}). Ohne sie behält der Aufräumjob die "
                f"Monatskopien zwölf Monate, und die Löschzusage zum "
                f"{row.purge_due_at.date().isoformat()} wird nicht eingehalten. "
                f"Von Hand anlegen: "
                f"{Path(settings.backup_share_root) / tenant.slug / OFFBOARDING_MARKER}"
            )
            logger.error("%s", warning)
    elif not settings.backup_share_root:
        warning = (
            "COCKPIT_BACKUP_SHARE_ROOT ist nicht gesetzt — es wurde keine "
            "Offboarding-Markierung geschrieben. Der Aufräumjob behält die "
            "Monatskopien damit zwölf Monate."
        )
        logger.warning("%s", warning)

    out = await _serialized(session, row)
    return out.model_copy(update={"warning": warning}) if warning else out


@router.post("/purged", response_model=OffboardingOut)
async def mark_purged(
    tenant_id: UUID, session: AsyncSession = Depends(get_session)
) -> OffboardingOut:
    """Fristablauf vermerken — erst wenn er wirklich eingetreten ist."""
    await _tenant(session, tenant_id)
    row = await _row(session, tenant_id)
    try:
        row = await flow.mark_purged(session, row)
    except flow.OffboardingError as exc:
        raise _conflict(exc) from exc
    return await _serialized(session, row)


@router.post("/abort", response_model=OffboardingOut)
async def abort_offboarding(
    tenant_id: UUID,
    body: OffboardingAbort,
    session: AsyncSession = Depends(get_session),
) -> OffboardingOut:
    """Kündigung zurückziehen. Nur solange nichts gelöscht ist."""
    tenant = await _tenant(session, tenant_id)
    row = await _row(session, tenant_id)
    try:
        row = await flow.abort(session, tenant, row, reason=body.reason)
    except flow.OffboardingError as exc:
        raise _conflict(exc) from exc
    return await _serialized(session, row)


__all__ = ["router"]
