"""Zustandsmeldung, Wartungsaufträge, versiegelte Geheimnisse (ADR-0024)."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from cockpit_api.models.operations import MaintenanceAction, MaintenanceState


class ReconcileStatus(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ok: bool
    at: datetime
    #: Ein Satz, kein Stacktrace. Ohne Token, ohne DSN — die Datenebene kürzt.
    error: str | None = Field(default=None, max_length=500)
    touched: bool = False


class AdSyncStatus(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: Kann ein Abgleich überhaupt laufen? Ohne Suchbasis nicht.
    configured: bool
    #: Welche Einstellungen fehlen, als Schlüsselnamen (`ad_users_search_base`).
    missing: list[str] = Field(default_factory=list, max_length=20)
    #: `connector`, `ldap` oder `mock`.
    backend: str | None = Field(default=None, max_length=16)
    last_success_at: datetime | None = None
    last_failure_at: datetime | None = None
    last_count: int | None = None
    last_mode: str | None = Field(default=None, max_length=16)


class MaintenanceResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    ok: bool
    #: Zählerstände oder ein Fehlercode — keine Namen, keine Personendaten.
    result: dict[str, int | str] = Field(default_factory=dict)


class StatusReport(BaseModel):
    """Was die Datenebene je Kunde meldet. Keine Personendaten, keine Geheimnisse."""

    model_config = ConfigDict(extra="forbid")

    reconcile: ReconcileStatus
    effective_profile: str | None = Field(default=None, max_length=16)
    enabled_modules: list[str] = Field(default_factory=list, max_length=40)
    ad: AdSyncStatus | None = None
    #: Öffentlicher Schlüssel zum Versiegeln (X25519, base64url) und sein
    #: Fingerabdruck. Öffentlich — damit versiegelt die Konsole, öffnen kann
    #: sie nichts.
    sealed_public_key: str | None = Field(default=None, max_length=64)
    sealed_key_id: str | None = Field(default=None, max_length=64)
    #: Welche Geheimnisse im Kundenschema gesetzt sind — nur ob, nie was.
    secrets_present: dict[str, bool] = Field(default_factory=dict)
    maintenance: list[MaintenanceResult] = Field(
        default_factory=list[MaintenanceResult], max_length=50
    )


class StatusOut(BaseModel):
    reported_at: datetime | None
    report: StatusReport | None
    #: Das Profil am Kunden in der Konsole — zum Vergleich mit dem gemeldeten.
    console_profile: str
    #: `False`, wenn Konsole und Installation verschiedene Profile haben.
    profile_matches: bool | None


class MaintenanceRequestIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: MaintenanceAction
    #: Für das Protokoll des Kunden: warum gelöscht wird.
    reason: str = Field(min_length=10, max_length=500)
    #: Zur Bestätigung den Kürzel des Kunden eintippen — gelöscht wird nicht
    #: aus Versehen beim falschen Kunden.
    confirm_slug: str


class MaintenanceRequestOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    action: MaintenanceAction
    state: MaintenanceState
    reason: str
    requested_by: str
    requested_at: datetime
    finished_at: datetime | None
    result: dict[str, Any] | None


class SealedSecretIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: Klartext, genau einmal über TLS. Die Konsole versiegelt ihn sofort und
    #: speichert nur das Chiffrat.
    value: str = Field(min_length=1, max_length=4096)


class SealedSecretOut(BaseModel):
    name: str
    #: Gesetzt in der Konsole (Chiffrat vorhanden)?
    sealed: bool
    #: Passt der Schlüssel noch zu dem, den die Datenebene meldet?
    key_current: bool | None
    #: Meldet die Datenebene das Geheimnis als im Kundenschema gesetzt?
    present_in_tenant: bool | None
    updated_at: datetime | None
    updated_by: str | None
