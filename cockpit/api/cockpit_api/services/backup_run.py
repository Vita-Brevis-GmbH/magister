"""Eine Sicherung ziehen — für den Knopf in der Konsole und den Zeitplaner.

Herausgelöst aus ``routers/backups.py``, damit die tägliche Sicherung
(ADR-0024 D6) denselben Code benutzt wie „Sicherung jetzt" — mit derselben
Monatskopie-Regel (E15), derselben Fehlerspur und demselben
Aufbewahrungs-Hinweis. Zwei Wege zum selben Dump wären zwei Stellen, an denen
eine Regel vergessen wird.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from cockpit_api.config import settings
from cockpit_api.models import (
    BackupKind,
    BackupStatus,
    Tenant,
    TenantBackup,
    TenantBackupPolicy,
    TenantOffboarding,
)
from cockpit_api.services.backup import BackupError, create_backup, write_retention_hint
from cockpit_api.services.backup_policy import keep_for, monthly_exists, resolve_kind

logger = logging.getLogger(__name__)


class BackupSetupError(RuntimeError):
    """Die Konsole ist für Sicherungen nicht eingerichtet (DSN oder Ablage fehlt)."""


def tenant_dsn_for_reading(tenant: Tenant) -> str:
    """Verwaltungszugang in den Cluster des Kunden.

    Für Sicherung und Export wird als Administrator gelesen, nicht als
    Mandantenrolle: ``pg_dump --schema=`` braucht Leserechte auf allen
    Objekten des Schemas, und der Export liest quer über alle Tabellen. Die
    Mandantenrolle hätte sie, aber ihr Passwort liegt nicht in der Konsole —
    genau so ist es gedacht (ADR-0013 D2).
    """
    if not settings.tenant_admin_dsn:
        raise BackupSetupError("COCKPIT_TENANT_ADMIN_DSN ist nicht gesetzt.")
    _ = tenant
    return settings.tenant_admin_dsn


def share_root(policy: TenantBackupPolicy | None) -> Path:
    root = (policy.share_root if policy and policy.share_root else "") or settings.backup_share_root
    if not root:
        raise BackupSetupError("COCKPIT_BACKUP_SHARE_ROOT ist nicht gesetzt.")
    return Path(root)


async def perform_backup(
    session: AsyncSession, tenant: Tenant, requested: BackupKind
) -> TenantBackup:
    """Sicherung ziehen und die Zeile schreiben (inklusive Commit).

    Wirft :class:`BackupSetupError`, wenn die Konsole nicht eingerichtet ist.
    Ein gescheiterter Dump wirft **nicht**: die Zeile steht dann auf
    ``failed`` und trägt den Grund.
    """
    policy = await session.get(TenantBackupPolicy, tenant.id)
    root = share_root(policy)
    dsn = tenant_dsn_for_reading(tenant)
    # Die erste geglückte Sicherung eines Kalendermonats wird zur Monatskopie
    # (E15). Kein zweiter Dump: derselbe Dump, nur mit längerer Frist. Der
    # Aufrufer bekommt in der Antwort die tatsächliche Art — die Cron-Zeile
    # bleibt unverändert `{"kind":"daily"}`.
    kind = resolve_kind(
        requested,
        policy=policy,
        monthly_present=await monthly_exists(session, tenant.id),
    )
    if kind is not requested:
        logger.info(
            "Sicherung für %s wird als %s geschrieben (%s), nicht als %s: "
            "erste Sicherung dieses Monats.",
            tenant.slug,
            kind.value,
            keep_for(kind, policy),
            requested.value,
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
            dsn=dsn,
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


__all__ = ["BackupSetupError", "perform_backup", "share_root", "tenant_dsn_for_reading"]
