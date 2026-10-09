"""Antwortformen für Sicherung, Wiederherstellung, Export, Offboarding (ADR-0016).

Kein Feld hier trägt ein Geheimnis. Was auffällt, ist die Menge an
*Zeitpunkten*: das ist der Punkt der Sache. Eine Sicherung, die „existiert",
sagt nichts; eine, die am 8.9. geschrieben und am 9.9. erfolgreich
eingespielt wurde, ist eine Zusage. Und beim Offboarding sind die Fristen der
Inhalt — der Kunde bekommt ein Datum genannt, und dieses Datum muss aus einer
Zeile lesbar sein und nicht aus einem Runbook.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from cockpit_api.models.backup import BackupKind, BackupStatus, ExportState, RestoreState
from cockpit_api.models.offboarding import OffboardingState


class BackupOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    kind: BackupKind
    status: BackupStatus
    path: str
    size_bytes: int | None
    checksum_sha256: str | None
    audit_key_id: str | None
    schema_version: str | None
    started_at: datetime
    finished_at: datetime | None
    verified_at: datetime | None
    verify_detail: str | None
    error: str | None


class BackupCreate(BaseModel):
    kind: BackupKind = BackupKind.manual


class BackupPolicyOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    tenant_id: UUID
    retention_days: int
    pre_migration_retention_days: int
    monthly_enabled: bool
    monthly_keep: int
    rpo_hours: int
    rto_hours: int
    share_root: str | None
    updated_at: datetime


class BackupPolicyUpdate(BaseModel):
    """Vertragswerte. Alle Felder freiwillig; nur Gesetztes wird geändert."""

    #: Entscheid E14: 10 Tage. Dieselbe Zahl ist Wiederherstellungszusage,
    #: Löschfrist beim Offboarding und der Wert in Vertrag und AVV — sie hier
    #: zu ändern ändert also eine Vertragszusage. Deshalb eine Untergrenze:
    #: unter einem Tag gibt es keine sinnvolle Zusage.
    retention_days: int | None = Field(default=None, ge=1, le=3650)
    pre_migration_retention_days: int | None = Field(default=None, ge=1, le=3650)
    #: Monatskopien (E15). Abschalten ist zulässig und eine Vertragsfrage —
    #: ohne sie ist ein Fehler, der erst am Quartalsende auffällt, nicht
    #: rückholbar.
    monthly_enabled: bool | None = None
    #: Anzahl, nicht Tage. Untergrenze 1: „null Monatskopien" heisst
    #: ``monthly_enabled: false`` und soll nicht über zwei Wege erreichbar
    #: sein.
    monthly_keep: int | None = Field(default=None, ge=1, le=120)
    rpo_hours: int | None = Field(default=None, ge=1, le=8760)
    rto_hours: int | None = Field(default=None, ge=1, le=8760)
    share_root: str | None = None


class RestoreRequest(BaseModel):
    backup_id: UUID
    #: Grund oder Ticket. Pflicht — eine Wiederherstellung ohne Anlass ist
    #: entweder ein Test oder ein Zugriff, und beides will man benannt haben.
    reason: str = Field(min_length=3, max_length=500)
    requested_by: str = Field(min_length=1, max_length=200)


class RestoreApprove(BaseModel):
    """Freigabe zum Umschalten — die **zweite** Person (ADR-0016 D5)."""

    approved_by: str = Field(min_length=1, max_length=200)


class RestoreJobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    backup_id: UUID
    target_schema: str
    state: RestoreState
    reason: str
    requested_by: str
    approved_by: str | None
    approved_at: datetime | None
    switched_at: datetime | None
    previous_schema: str | None
    error: str | None
    created_at: datetime
    finished_at: datetime | None


class ExportRequest(BaseModel):
    requested_by: str = Field(min_length=1, max_length=200)


class ExportJobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    state: ExportState
    path: str | None
    size_bytes: int | None
    checksum_sha256: str | None
    requested_by: str
    expires_at: datetime | None
    downloaded_at: datetime | None
    error: str | None
    created_at: datetime


class OffboardingStart(BaseModel):
    reason: str = Field(min_length=3, max_length=500)
    requested_by: str = Field(min_length=1, max_length=200)
    #: Vertragswert, Vorgabe 30 Tage. ``0`` ist zulässig, aber nur
    #: ausdrücklich — es heisst „sofort löschbar" und gehört in einen Vertrag,
    #: nicht in eine Vorgabe.
    grace_days: int = Field(default=30, ge=0, le=3650)


class OffboardingDrop(BaseModel):
    """Löschen von Schema und Rolle — zwei Personen, unwiderruflich."""

    dropped_by: str = Field(min_length=1, max_length=200)
    approved_by: str = Field(min_length=1, max_length=200)


class OffboardingKeyDestroyed(BaseModel):
    confirmed_by: str = Field(min_length=1, max_length=200)


class OffboardingAbort(BaseModel):
    reason: str = Field(min_length=3, max_length=500)


class OffboardingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    tenant_id: UUID
    state: OffboardingState
    reason: str
    requested_by: str
    requested_at: datetime
    grace_days: int
    grace_until: datetime
    final_backup_id: UUID | None
    export_job_id: UUID | None
    export_delivered_at: datetime | None
    dropped_at: datetime | None
    dropped_by: str | None
    approved_by: str | None
    key_destroyed_at: datetime | None
    key_destroyed_by: str | None
    key_id: str | None
    purge_due_at: datetime | None
    purged_at: datetime | None
    aborted_at: datetime | None
    aborted_reason: str | None
    updated_at: datetime
    #: Gesetzt, wenn ein Schritt geglückt ist, aber etwas daneben nicht.
    #: Konkret: der Kundenschlüssel ist vernichtet (unwiderruflich), die
    #: Markierung für den Aufräumjob liess sich aber nicht schreiben — dann
    #: läuft eine Frist, die niemand einhält, und das darf nicht in einer
    #: Protokollzeile untergehen.
    warning: str | None = None


__all__ = [
    "BackupCreate",
    "BackupOut",
    "BackupPolicyOut",
    "BackupPolicyUpdate",
    "ExportJobOut",
    "ExportRequest",
    "OffboardingAbort",
    "OffboardingDrop",
    "OffboardingKeyDestroyed",
    "OffboardingOut",
    "OffboardingStart",
    "RestoreApprove",
    "RestoreJobOut",
    "RestoreRequest",
]
