"""Sicherung, Wiederherstellung, Export (ADR-0016 D10).

Was hier steht, ist **Buchhaltung über** Sicherungen, nicht die Sicherung
selbst. Die Dumps liegen auf einem Share; die Konsole weiss, welche es gibt,
wie gross sie sind, mit welchem Kundenschlüssel ihre Audit-Payloads
verschlüsselt sind und wann eine Prüf-Wiederherstellung zuletzt geglückt ist.

Zwei Dinge stehen hier **nicht**:

* **Kein privater Schlüssel.** Verschlüsselt wird mit dem öffentlichen
  Plattform-Backup-Schlüssel (``age``); der private liegt getrennt und wird auf
  dem Anwendungsserver nie gebraucht (ADR-0016 D2).
* **Kein Kundenschlüssel.** ``audit_key_id`` ist ein Verweis. Wer
  wiederherstellt, braucht beide Quellen — Dump und Schlüsseltresor. Genau so
  ist es gedacht: ein gestohlenes Backup gibt ohne den Kundenschlüssel keine
  Audit-Payloads her.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, Integer, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from cockpit_api.models.base import Base, enum_column


class BackupKind(enum.StrEnum):
    """Art der Sicherung. Bestimmt die Aufbewahrung."""

    daily = "daily"
    #: Vor jeder Migration (ADR-0016 D6). Wird 30 Tage gehalten, unabhängig
    #: von der normalen Frist — es ist die Rückfahrkarte für eine misslungene
    #: Migration, und die merkt man nicht immer am selben Tag.
    pre_migration = "pre_migration"
    manual = "manual"
    #: Vor dem Offboarding, als letzter Stand.
    offboarding = "offboarding"


class BackupStatus(enum.StrEnum):
    running = "running"
    #: Geschrieben, aber noch nicht eingespielt. Ein Backup in diesem Zustand
    #: ist eine Hoffnung, keine Zusage (ADR-0016 D4).
    written = "written"
    verified = "verified"
    failed = "failed"
    #: Vom Aufräumjob auf dem Fileserver entfernt. Magister löscht nicht
    #: selbst (ADR-0016 D2).
    pruned = "pruned"


class RestoreState(enum.StrEnum):
    requested = "requested"
    running = "running"
    #: Im Nebenschema eingespielt und lesbar. Umschalten ist ein eigener
    #: Schritt mit zweiter Person (ADR-0016 D5).
    restored = "restored"
    switched = "switched"
    failed = "failed"
    discarded = "discarded"


class ExportState(enum.StrEnum):
    requested = "requested"
    running = "running"
    ready = "ready"
    downloaded = "downloaded"
    expired = "expired"
    failed = "failed"


class TenantBackup(Base):
    __tablename__ = "tenant_backups"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[BackupKind] = mapped_column(
        enum_column(BackupKind, name="backup_kind"), default=BackupKind.daily
    )
    status: Mapped[BackupStatus] = mapped_column(
        enum_column(BackupStatus, name="backup_status"), default=BackupStatus.running
    )
    #: Pfad auf dem Share. Kein Geheimnis: die Datei ist verschlüsselt.
    path: Mapped[str] = mapped_column(String(1000))
    size_bytes: Mapped[int | None] = mapped_column(BigInteger, default=None)
    #: SHA-256 über die **verschlüsselte** Datei, hex. Prüft, ob der Share die
    #: Datei unverändert hält — und ist die Grundlage dafür, einen beschädigten
    #: Dump als beschädigt zu erkennen und nicht als unlesbar.
    checksum_sha256: Mapped[str | None] = mapped_column(String(64), default=None)
    #: Verweis auf den Kundenschlüssel, mit dem die Audit-Payloads im Dump
    #: verschlüsselt sind. Nie der Schlüssel selbst.
    audit_key_id: Mapped[str | None] = mapped_column(String(64), default=None)
    #: Alembic-Revision des Schemas zum Zeitpunkt der Sicherung. Ohne sie
    #: weiss man beim Wiederherstellen nicht, welcher Codestand dazu passt.
    schema_version: Mapped[str | None] = mapped_column(String(64), default=None)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    #: Wann die Prüf-Wiederherstellung zuletzt geglückt ist (ADR-0016 D4).
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    verify_detail: Mapped[str | None] = mapped_column(String(2000), default=None)
    error: Mapped[str | None] = mapped_column(String(2000), default=None)

    __table_args__ = (Index("ix_tenant_backups_lookup", "tenant_id", "kind", "started_at"),)


class TenantBackupPolicy(Base):
    """Aufbewahrung und Zusagen pro Kunde — die Vertragswerte."""

    __tablename__ = "tenant_backup_policy"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), primary_key=True
    )
    #: Entscheid E14: 10 Tage. Dieselbe Zahl ist Wiederherstellungszusage,
    #: Löschfrist beim Offboarding und der Wert in Vertrag und AVV.
    retention_days: Mapped[int] = mapped_column(Integer, default=10)
    #: Vor-Migrations-Dumps werden länger gehalten (ADR-0016 D6).
    pre_migration_retention_days: Mapped[int] = mapped_column(Integer, default=30)
    #: Zielwerte für den Vertrag. Die Konsole zeigt sie neben dem tatsächlich
    #: Erreichten, damit eine Zusage nicht nur im Vertrag steht.
    rpo_hours: Mapped[int] = mapped_column(Integer, default=24)
    rto_hours: Mapped[int] = mapped_column(Integer, default=8)
    #: Wurzelverzeichnis auf dem Share. Leer heisst: Vorgabe der Installation.
    share_root: Mapped[str | None] = mapped_column(String(500), default=None)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class RestoreJob(Base):
    """Eine Wiederherstellung — immer daneben, nie darüber (ADR-0016 D5)."""

    __tablename__ = "restore_jobs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), index=True
    )
    backup_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenant_backups.id", ondelete="RESTRICT")
    )
    #: Zielschema, immer neu: ``r_<slug>_<zeitstempel>``. Nie das Produktivschema.
    target_schema: Mapped[str] = mapped_column(String(63))
    state: Mapped[RestoreState] = mapped_column(
        enum_column(RestoreState, name="restore_state"), default=RestoreState.requested
    )
    #: Grund oder Ticket. Pflicht — eine Wiederherstellung ohne Anlass ist
    #: entweder ein Test oder ein Zugriff, und beides will man benannt haben.
    reason: Mapped[str] = mapped_column(String(500))
    requested_by: Mapped[str] = mapped_column(String(200))
    #: Umschalten verlangt eine **zweite** Person (ADR-0016 D5).
    approved_by: Mapped[str | None] = mapped_column(String(200), default=None)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    switched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    #: Schema, das beim Umschalten verdrängt wurde. Es bleibt stehen — der
    #: Rückweg, wenn sich die Wiederherstellung als falsch erweist.
    previous_schema: Mapped[str | None] = mapped_column(String(63), default=None)
    error: Mapped[str | None] = mapped_column(String(2000), default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)


class ExportJob(Base):
    """Ein Export für den Kunden (ADR-0016 D7) — kein umbenanntes Backup."""

    __tablename__ = "export_jobs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), index=True
    )
    state: Mapped[ExportState] = mapped_column(
        enum_column(ExportState, name="export_state"), default=ExportState.requested
    )
    path: Mapped[str | None] = mapped_column(String(1000), default=None)
    size_bytes: Mapped[int | None] = mapped_column(BigInteger, default=None)
    checksum_sha256: Mapped[str | None] = mapped_column(String(64), default=None)
    requested_by: Mapped[str] = mapped_column(String(200))
    #: Der Download läuft ab. Ein Export enthält alle Personendaten eines
    #: Kunden; ein Link, der ewig gilt, ist ein Datenleck mit Verfallsdatum
    #: „nie".
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    downloaded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    error: Mapped[str | None] = mapped_column(String(2000), default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
