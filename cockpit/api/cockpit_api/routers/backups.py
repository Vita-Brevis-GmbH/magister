"""Sicherung, Prüfung, Wiederherstellung, Export (ADR-0016).

**Was die Konsole selbst kann und was nicht** — das ist die wichtigste Zeile
dieses Moduls, und sie folgt direkt aus der Schlüsseltrennung in D2:

* **Sichern: ja.** Dafür braucht es nur den *öffentlichen* age-Schlüssel.
* **Exportieren: ja.** Der Export liest das Kundenschema und schreibt Klartext;
  ein Backup-Schlüssel kommt darin nicht vor.
* **Wiederherstellen und prüfen: nein.** Beides muss *entschlüsseln*, und der
  private Schlüssel liegt nicht auf dem Anwendungsserver — genau das ist die
  Zusage. Diese Endpunkte **erfassen** deshalb einen Auftrag und **nehmen ein
  Ergebnis entgegen**, das der Backup-Host meldet. Sie führen nichts aus.

Ein Endpunkt, der eine Wiederherstellung „auslöst", wäre bequemer und würde
die Zusage aus D2 aufheben: dann läge der private Schlüssel dort, wo auch die
Anwendung läuft, und ein übernommener Anwendungsserver könnte alle alten
Sicherungen lesen. Die Umständlichkeit ist der Zweck.

Das Umschalten auf eine Wiederherstellung verlangt eine zweite Person
(D5) — und ist hier bewusst nur ein **Vermerk**: welche Datenbank und welches
Schema für einen Kunden gelten, entscheidet die Registry, und die
Betriebsschritte dazu stehen in
``docs/runbooks/sicherung-wiederherstellung.md``.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from cockpit_api.auth import require_bootstrap_token
from cockpit_api.config import settings
from cockpit_api.db import get_session
from cockpit_api.models import (
    BackupStatus,
    ExportJob,
    ExportState,
    PlatformHeartbeat,
    RestoreJob,
    RestoreState,
    Tenant,
    TenantBackup,
    TenantBackupPolicy,
)
from cockpit_api.schemas.backup import (
    BackupCreate,
    BackupOut,
    BackupPolicyOut,
    BackupPolicyUpdate,
    ExportJobOut,
    ExportRequest,
    RestoreApprove,
    RestoreJobOut,
    RestoreRequest,
)
from cockpit_api.services.backup_run import (
    BackupSetupError,
    perform_backup,
    tenant_dsn_for_reading,
)
from cockpit_api.services.export import ExportError, create_export
from cockpit_api.services.restore import RESTORE_DB_PATTERN, scratch_database_name

logger = logging.getLogger(__name__)

router = APIRouter(tags=["backup"], dependencies=[Depends(require_bootstrap_token)])


async def _tenant(session: AsyncSession, tenant_id: UUID) -> Tenant:
    tenant = await session.get(Tenant, tenant_id)
    if tenant is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "unknown tenant")
    return tenant


def _tenant_dsn_for_reading(tenant: Tenant) -> str:
    try:
        return tenant_dsn_for_reading(tenant)
    except BackupSetupError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc


# --- Sicherungen ----------------------------------------------------------


@router.get("/tenants/{tenant_id}/backups", response_model=list[BackupOut])
async def list_backups(
    tenant_id: UUID, session: AsyncSession = Depends(get_session)
) -> list[TenantBackup]:
    await _tenant(session, tenant_id)
    stmt = (
        select(TenantBackup)
        .where(TenantBackup.tenant_id == tenant_id)
        .order_by(TenantBackup.started_at.desc())
    )
    return list((await session.execute(stmt)).scalars().all())


@router.post(
    "/tenants/{tenant_id}/backups",
    response_model=BackupOut,
    status_code=status.HTTP_201_CREATED,
)
async def run_backup(
    tenant_id: UUID,
    body: BackupCreate,
    session: AsyncSession = Depends(get_session),
) -> TenantBackup:
    """Eine Sicherung jetzt ziehen.

    Läuft **im Aufruf** und nicht im Hintergrund: ein ``pg_dump`` eines
    Schulschemas ist eine Sache von Sekunden bis Minuten, und ein Aufrufer,
    der auf die Antwort wartet, erfährt sofort, ob es geklappt hat. Der Preis
    ist ein länger offener Request; die Alternative wäre eine Warteschlange
    für einen Vorgang, der einmal am Tag läuft.

    Bricht der Prozess mitten in der Sicherung ab, bleibt die Zeile auf
    ``running`` stehen. Das ist sichtbar und richtig — ``running`` seit drei
    Stunden ist eine Information, ein stilles Verschwinden nicht.
    """
    tenant = await _tenant(session, tenant_id)
    try:
        return await perform_backup(session, tenant, body.kind)
    except BackupSetupError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc


@router.post("/backups/{backup_id}/verify-result", response_model=BackupOut)
async def report_verify_result(
    backup_id: UUID,
    ok: bool,
    detail: str = "",
    session: AsyncSession = Depends(get_session),
) -> TenantBackup:
    """Ergebnis einer Prüf-Wiederherstellung entgegennehmen (ADR-0016 D4).

    Gemeldet vom Backup-Host, weil nur dort der private Schlüssel liegt. Die
    Konsole prüft **nicht** selbst und tut auch nicht so: ``verified_at`` wird
    nur gesetzt, wenn eine erfolgreiche Prüfung gemeldet wurde.
    """
    row = await session.get(TenantBackup, backup_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "unknown backup")
    row.verify_detail = detail[:2000] or None
    if ok:
        row.verified_at = datetime.now(UTC)
        row.status = BackupStatus.verified
    else:
        row.status = BackupStatus.failed
        row.error = (detail or "Prüf-Wiederherstellung gescheitert")[:2000]
    await session.commit()
    await session.refresh(row)
    return row


# --- Prüfer auf dem Backup-Host (ADR-0024 D6) ------------------------------

#: Name des Lebenszeichens, unter dem sich der Prüfer meldet.
WORKER_HEARTBEAT = "backup-worker"


class WorkerVerifyItem(BaseModel):
    backup_id: UUID
    tenant_slug: str
    schema_name: str
    path: str
    checksum_sha256: str | None
    schema_version: str | None


class WorkerRestoreItem(BaseModel):
    job_id: UUID
    tenant_slug: str
    path: str
    checksum_sha256: str | None
    target_database: str


class WorkerQueue(BaseModel):
    verify: list[WorkerVerifyItem]
    restore: list[WorkerRestoreItem]


class WorkerHeartbeatOut(BaseModel):
    last_seen_at: datetime | None
    detail: str | None


@router.get("/backups/worker-queue", response_model=WorkerQueue)
async def worker_queue(
    detail: str = "", session: AsyncSession = Depends(get_session)
) -> WorkerQueue:
    """Was der Prüfer tun soll — und zugleich sein Lebenszeichen.

    Der Prüfer läuft dort, wo der private Backup-Schlüssel liegt (ADR-0016
    D2), und holt sich hier seine Arbeit: geschriebene, noch ungeprüfte
    Sicherungen und erfasste Wiederherstellungen. Die Ergebnisse meldet er
    über die bestehenden Endpunkte. Die Konsole führt weiterhin nichts aus.

    Der Abruf vermerkt das Lebenszeichen. Ohne ihn hiesse „nie geprüft"
    entweder „noch nicht dran" oder „Prüfer läuft gar nicht" — die Oberfläche
    zeigt jetzt, welches von beiden.
    """
    beat = await session.get(PlatformHeartbeat, WORKER_HEARTBEAT)
    if beat is None:
        session.add(PlatformHeartbeat(name=WORKER_HEARTBEAT, detail=detail[:2000] or None))
    else:
        beat.last_seen_at = datetime.now(UTC)
        beat.detail = detail[:2000] or None

    pending = (
        await session.execute(
            select(TenantBackup, Tenant)
            .join(Tenant, Tenant.id == TenantBackup.tenant_id)
            .where(TenantBackup.status == BackupStatus.written)
            .order_by(TenantBackup.started_at)
            .limit(5)
        )
    ).all()
    restores = (
        await session.execute(
            select(RestoreJob, TenantBackup, Tenant)
            .join(TenantBackup, TenantBackup.id == RestoreJob.backup_id)
            .join(Tenant, Tenant.id == RestoreJob.tenant_id)
            .where(RestoreJob.state == RestoreState.requested)
            .order_by(RestoreJob.created_at)
            .limit(3)
        )
    ).all()
    await session.commit()
    return WorkerQueue(
        verify=[
            WorkerVerifyItem(
                backup_id=b.id,
                tenant_slug=t.slug,
                schema_name=t.schema_name,
                path=b.path,
                checksum_sha256=b.checksum_sha256,
                schema_version=b.schema_version,
            )
            for b, t in pending
        ],
        restore=[
            WorkerRestoreItem(
                job_id=j.id,
                tenant_slug=t.slug,
                path=b.path,
                checksum_sha256=b.checksum_sha256,
                target_database=j.target_schema,
            )
            for j, b, t in restores
        ],
    )


@router.get("/backups/worker", response_model=WorkerHeartbeatOut)
async def worker_status(session: AsyncSession = Depends(get_session)) -> WorkerHeartbeatOut:
    beat = await session.get(PlatformHeartbeat, WORKER_HEARTBEAT)
    return WorkerHeartbeatOut(
        last_seen_at=beat.last_seen_at if beat else None, detail=beat.detail if beat else None
    )


# --- Aufbewahrung ---------------------------------------------------------


@router.get("/tenants/{tenant_id}/backup-policy", response_model=BackupPolicyOut)
async def get_policy(
    tenant_id: UUID, session: AsyncSession = Depends(get_session)
) -> TenantBackupPolicy:
    await _tenant(session, tenant_id)
    policy = await session.get(TenantBackupPolicy, tenant_id)
    if policy is None:
        # Vorgabewerte sichtbar machen statt 404: ein Kunde ohne eigene Zeile
        # hat trotzdem eine Aufbewahrungsfrist, und die soll man sehen.
        policy = TenantBackupPolicy(tenant_id=tenant_id)
        session.add(policy)
        await session.commit()
        await session.refresh(policy)
    return policy


@router.put("/tenants/{tenant_id}/backup-policy", response_model=BackupPolicyOut)
async def update_policy(
    tenant_id: UUID,
    body: BackupPolicyUpdate,
    session: AsyncSession = Depends(get_session),
) -> TenantBackupPolicy:
    """Vertragswerte ändern.

    ``retention_days`` ist gleichzeitig Wiederherstellungszusage, Löschfrist
    beim Offboarding und der Wert in Vertrag und AVV (ADR-0016 D3). Eine
    Änderung hier ändert also eine Zusage — deshalb wird sie protokolliert.
    """
    await _tenant(session, tenant_id)
    policy = await session.get(TenantBackupPolicy, tenant_id)
    if policy is None:
        policy = TenantBackupPolicy(tenant_id=tenant_id)
        session.add(policy)
    changes = body.model_dump(exclude_unset=True, exclude_none=True)
    for field, value in changes.items():
        setattr(policy, field, value)
    await session.commit()
    await session.refresh(policy)
    if changes:
        logger.info("Aufbewahrung für Kunde %s geändert: %s", tenant_id, changes)
    return policy


# --- Wiederherstellung ----------------------------------------------------


@router.get("/tenants/{tenant_id}/restore-jobs", response_model=list[RestoreJobOut])
async def list_restore_jobs(
    tenant_id: UUID, session: AsyncSession = Depends(get_session)
) -> list[RestoreJob]:
    await _tenant(session, tenant_id)
    stmt = (
        select(RestoreJob)
        .where(RestoreJob.tenant_id == tenant_id)
        .order_by(RestoreJob.created_at.desc())
    )
    return list((await session.execute(stmt)).scalars().all())


@router.post(
    "/tenants/{tenant_id}/restore-jobs",
    response_model=RestoreJobOut,
    status_code=status.HTTP_201_CREATED,
)
async def request_restore(
    tenant_id: UUID,
    body: RestoreRequest,
    session: AsyncSession = Depends(get_session),
) -> RestoreJob:
    """Eine Wiederherstellung **erfassen** — nicht ausführen.

    Ausgeführt wird sie auf dem Backup-Host, weil nur dort der private
    Schlüssel liegt (ADR-0016 D2). Diese Zeile ist der Auftrag dazu und der
    Ort, an dem Grund, Freigabe und Ergebnis zusammenkommen.
    """
    tenant = await _tenant(session, tenant_id)
    backup = await session.get(TenantBackup, body.backup_id)
    if backup is None or backup.tenant_id != tenant.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "unknown backup for this tenant")
    if backup.status is BackupStatus.pruned:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Diese Sicherung ist abgelaufen und vom Aufräumjob entfernt.",
        )
    row = RestoreJob(
        tenant_id=tenant.id,
        backup_id=backup.id,
        target_schema=scratch_database_name(RESTORE_DB_PATTERN, tenant.slug)[:63],
        state=RestoreState.requested,
        reason=body.reason,
        requested_by=body.requested_by,
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)
    logger.info(
        "Wiederherstellung für %s erfasst (%s): %s", tenant.slug, body.requested_by, body.reason
    )
    return row


@router.post("/restore-jobs/{job_id}/report", response_model=RestoreJobOut)
async def report_restore(
    job_id: UUID,
    ok: bool,
    detail: str = "",
    session: AsyncSession = Depends(get_session),
) -> RestoreJob:
    """Der Backup-Host meldet das Ergebnis."""
    row = await session.get(RestoreJob, job_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "unknown restore job")
    row.state = RestoreState.restored if ok else RestoreState.failed
    row.error = None if ok else (detail or "Wiederherstellung gescheitert")[:2000]
    row.finished_at = datetime.now(UTC)
    await session.commit()
    await session.refresh(row)
    return row


@router.post("/restore-jobs/{job_id}/approve", response_model=RestoreJobOut)
async def approve_restore(
    job_id: UUID,
    body: RestoreApprove,
    session: AsyncSession = Depends(get_session),
) -> RestoreJob:
    """Freigabe zum Umschalten — die **zweite** Person (ADR-0016 D5).

    Verschieden von der bestellenden Person, und erst wenn die
    Wiederherstellung eingespielt und lesbar ist. Eine Freigabe für etwas, das
    noch nicht existiert, ist keine.
    """
    row = await session.get(RestoreJob, job_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "unknown restore job")
    if row.state is not RestoreState.restored:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Der Auftrag ist {row.state.value}. Freigegeben wird eine eingespielte "
            "und lesbare Wiederherstellung.",
        )
    if body.approved_by.strip().lower() == row.requested_by.strip().lower():
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Bestellende und freigebende Person müssen verschieden sein (ADR-0016 D5).",
        )
    row.approved_by = body.approved_by.strip()
    row.approved_at = datetime.now(UTC)
    await session.commit()
    await session.refresh(row)
    logger.info("Wiederherstellung %s freigegeben von %s", job_id, row.approved_by)
    return row


@router.post("/restore-jobs/{job_id}/switched", response_model=RestoreJobOut)
async def mark_switched(job_id: UUID, session: AsyncSession = Depends(get_session)) -> RestoreJob:
    """Das Umschalten **vermerken**, nachdem es betrieblich vollzogen ist.

    Wieso nur vermerken: die Wiederherstellung liegt in einer eigenen
    Datenbank, und welcher DSN für einen Kunden gilt, löst der
    Anwendungsserver aus seiner Umgebung auf (``MAGISTER_TENANT_DSN_<REF>``,
    ADR-0013 D2). Das Umschalten ist damit eine Konfigurationsänderung auf dem
    Anwendungsserver und keine Zeile in der Konsole — die Konsole hält fest,
    **dass** und **wann** es geschehen ist, und welches Schema verdrängt wurde.
    Der Ablauf steht in docs/runbooks/sicherung-wiederherstellung.md.
    """
    row = await session.get(RestoreJob, job_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "unknown restore job")
    if row.approved_at is None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Ohne Freigabe einer zweiten Person wird nicht umgeschaltet (ADR-0016 D5).",
        )
    tenant = await _tenant(session, row.tenant_id)
    row.previous_schema = tenant.schema_name
    row.switched_at = datetime.now(UTC)
    row.state = RestoreState.switched
    await session.commit()
    await session.refresh(row)
    logger.info(
        "Kunde %s auf Wiederherstellung %s umgeschaltet; vorheriges Schema %s bleibt stehen",
        tenant.slug,
        job_id,
        row.previous_schema,
    )
    return row


# --- Export ---------------------------------------------------------------


@router.get("/tenants/{tenant_id}/exports", response_model=list[ExportJobOut])
async def list_exports(
    tenant_id: UUID, session: AsyncSession = Depends(get_session)
) -> list[ExportJob]:
    await _tenant(session, tenant_id)
    stmt = (
        select(ExportJob)
        .where(ExportJob.tenant_id == tenant_id)
        .order_by(ExportJob.created_at.desc())
    )
    return list((await session.execute(stmt)).scalars().all())


@router.post(
    "/tenants/{tenant_id}/exports",
    response_model=ExportJobOut,
    status_code=status.HTTP_201_CREATED,
)
async def run_export(
    tenant_id: UUID,
    body: ExportRequest,
    session: AsyncSession = Depends(get_session),
) -> ExportJob:
    """Export erstellen (ADR-0016 D7).

    Der Download läuft ab (``COCKPIT_EXPORT_TTL_DAYS``). Ein Export enthält
    alle Personendaten eines Kunden im Klartext; ein Link, der ewig gilt, ist
    ein Datenleck mit Verfallsdatum „nie".
    """
    tenant = await _tenant(session, tenant_id)
    if not settings.export_root:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "COCKPIT_EXPORT_ROOT ist nicht gesetzt."
        )
    row = ExportJob(tenant_id=tenant.id, state=ExportState.running, requested_by=body.requested_by)
    session.add(row)
    await session.flush()
    try:
        artifact = await create_export(
            dsn=_tenant_dsn_for_reading(tenant),
            schema_name=tenant.schema_name,
            slug=tenant.slug,
            tenant_name=tenant.name,
            export_root=Path(settings.export_root),
        )
    except ExportError as exc:
        row.state = ExportState.failed
        row.error = str(exc)[:2000]
        await session.commit()
        await session.refresh(row)
        return row
    row.path = str(artifact.path)
    row.size_bytes = artifact.size_bytes
    row.checksum_sha256 = artifact.checksum_sha256
    expires = datetime.now(UTC) + timedelta(days=settings.export_ttl_days)
    row.expires_at = expires
    row.state = ExportState.ready
    await session.commit()
    await session.refresh(row)
    logger.info(
        "Export für %s erstellt (%d Bytes), Download bis %s",
        tenant.slug,
        artifact.size_bytes,
        expires.isoformat(),
    )
    return row


@router.get("/exports/{export_id}/download")
async def download_export(
    export_id: UUID, session: AsyncSession = Depends(get_session)
) -> FileResponse:
    """Zeitlich begrenzter Download, auditiert (ADR-0016 D7)."""
    row = await session.get(ExportJob, export_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "unknown export")
    if row.state not in (ExportState.ready, ExportState.downloaded) or not row.path:
        raise HTTPException(status.HTTP_409_CONFLICT, f"Der Export ist {row.state.value}.")
    now = datetime.now(UTC)
    if row.expires_at is not None and now > row.expires_at:
        row.state = ExportState.expired
        await session.commit()
        raise HTTPException(
            status.HTTP_410_GONE,
            f"Der Download war bis {row.expires_at.isoformat()} gültig. Neu bestellen.",
        )
    path = Path(row.path)
    if not path.is_file():
        raise HTTPException(
            status.HTTP_410_GONE,
            "Die Exportdatei liegt nicht mehr vor — die Frist ist abgelaufen "
            "und der Aufräumjob hat sie entfernt.",
        )
    row.downloaded_at = now
    row.state = ExportState.downloaded
    await session.commit()
    logger.info("Export %s heruntergeladen", export_id)
    return FileResponse(path, media_type="application/zip", filename=path.name)


__all__ = ["router"]
