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
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from cockpit_api.auth import require_bootstrap_token
from cockpit_api.config import settings
from cockpit_api.db import get_session
from cockpit_api.models import (
    BackupKind,
    BackupStatus,
    ExportJob,
    ExportState,
    RestoreJob,
    RestoreState,
    Tenant,
    TenantBackup,
    TenantBackupPolicy,
    TenantOffboarding,
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
from cockpit_api.services.backup import BackupError, create_backup, write_retention_hint
from cockpit_api.services.backup_policy import keep_for, monthly_exists, resolve_kind
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
    """Verwaltungszugang in den Cluster des Kunden.

    Für Sicherung und Export wird als Administrator gelesen, nicht als
    Mandantenrolle: ``pg_dump --schema=`` braucht Leserechte auf allen
    Objekten des Schemas, und der Export liest quer über alle Tabellen. Die
    Mandantenrolle hätte sie, aber ihr Passwort liegt nicht in der Konsole —
    genau so ist es gedacht (ADR-0013 D2).
    """
    if not settings.tenant_admin_dsn:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "COCKPIT_TENANT_ADMIN_DSN ist nicht gesetzt.",
        )
    _ = tenant
    return settings.tenant_admin_dsn


def _share_root(policy: TenantBackupPolicy | None) -> Path:
    root = (policy.share_root if policy and policy.share_root else "") or settings.backup_share_root
    if not root:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "COCKPIT_BACKUP_SHARE_ROOT ist nicht gesetzt.",
        )
    return Path(root)


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
    policy = await session.get(TenantBackupPolicy, tenant_id)
    root = _share_root(policy)
    # Die erste geglückte Sicherung eines Kalendermonats wird zur Monatskopie
    # (E15). Kein zweiter Dump: derselbe Dump, nur mit längerer Frist. Der
    # Aufrufer bekommt in der Antwort die tatsächliche Art — die Cron-Zeile
    # bleibt unverändert `{"kind":"daily"}`.
    kind = resolve_kind(
        body.kind,
        policy=policy,
        monthly_present=await monthly_exists(session, tenant_id),
    )
    if kind is not body.kind:
        logger.info(
            "Sicherung für %s wird als %s geschrieben (%s), nicht als %s: "
            "erste Sicherung dieses Monats.",
            tenant.slug,
            kind.value,
            keep_for(kind, policy),
            body.kind.value,
        )
    row = TenantBackup(
        tenant_id=tenant.id,
        kind=kind,
        status=BackupStatus.running,
        path="",
        audit_key_id=tenant.audit_key_id,
        schema_version=tenant.schema_version,
    )
    session.add(row)
    await session.flush()
    try:
        artifact = await create_backup(
            dsn=_tenant_dsn_for_reading(tenant),
            schema_name=tenant.schema_name,
            slug=tenant.slug,
            kind=kind.value,
            share_root=root,
            recipient=settings.backup_age_recipient,
        )
    except BackupError as exc:
        row.status = BackupStatus.failed
        row.error = str(exc)[:2000]
        row.finished_at = datetime.now(UTC)
        await session.commit()
        await session.refresh(row)
        # 201 mit failed und nicht 500: die Zeile *existiert* und trägt den
        # Grund. Ein 500 ohne Spur wäre die schlechtere Antwort.
        return row
    row.path = str(artifact.path)
    row.size_bytes = artifact.size_bytes
    row.checksum_sha256 = artifact.checksum_sha256
    row.status = BackupStatus.written
    row.finished_at = datetime.now(UTC)
    # Die Fristen neben die Dumps, damit der Aufräumjob auf dem Fileserver sie
    # nicht raten muss. Scheitert es, ist die Sicherung trotzdem gut — also
    # nur eine Warnung.
    try:
        write_retention_hint(
            root,
            tenant.slug,
            retention_days=policy.retention_days if policy else 10,
            pre_migration_retention_days=(policy.pre_migration_retention_days if policy else 30),
            monthly_keep=policy.monthly_keep if policy else 12,
        )
    except (BackupError, OSError) as exc:
        logger.warning(
            "Aufbewahrungs-Hinweis für %s nicht geschrieben (%s). Der "
            "Aufräumjob benutzt dann seine Vorgabewerte.",
            tenant.slug,
            exc,
        )
    if kind is BackupKind.offboarding:
        # Der letzte Stand vor dem Löschen gehört an die Offboarding-Zeile:
        # dort sucht man ihn, wenn ein gekündigter Kunde ein Jahr später
        # anruft. Ohne diese Zuordnung wäre er eine Datei unter vielen.
        off = await session.get(TenantOffboarding, tenant.id)
        if off is not None:
            off.final_backup_id = row.id
    await session.commit()
    await session.refresh(row)
    return row


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
