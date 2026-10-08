"""Betrieb aus der Konsole (ADR-0024).

Vier Tabellen, eine Frage: was die Konsole über die Installationen weiss und
was sie dort auslösen kann, **ohne** in deren Datenbank zu greifen.

* :class:`TenantStatusReport` — was die Datenebene über einen Kunden meldet:
  ob der Abgleich gelingt, welches Profil wirklich gilt, wie der AD-Sync
  steht. Vorher wusste die Konsole davon nichts, und „Profil auf Firma
  gestellt, Portal zeigt Schule" war von hier aus nicht zu erkennen.
* :class:`TenantSealedSecret` — ein Geheimnis (Entra-Client-Secret), mit dem
  öffentlichen Schlüssel der Datenebene versiegelt. Die Konsole hält das
  Chiffrat und kann es nicht öffnen.
* :class:`TenantMaintenanceRequest` — ein Wartungsauftrag (Demodaten
  entfernen, Protokoll zurücksetzen), den die Datenebene mit dem Soll-Zustand
  abholt, genau einmal ausführt und zurückmeldet.
* :class:`PlatformHeartbeat` — Lebenszeichen der Helfer ausserhalb der
  Konsole (Backup-Prüfer). Ohne sie hiesse „nie geprüft" entweder „noch nicht
  dran" oder „Prüfer läuft gar nicht", und das ist nicht dasselbe.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Enum, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from cockpit_api.models.base import Base


class TenantStatusReport(Base):
    """Die letzte Zustandsmeldung der Datenebene für einen Kunden. Eine Zeile je Kunde."""

    __tablename__ = "tenant_status_reports"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), primary_key=True
    )
    reported_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    #: Das gemeldete Dokument, geprüft gegen `schemas.operations.StatusReport`.
    #: Keine Personendaten: Zeitpunkte, Zählerstände, Profil, Ursachen-Codes.
    payload: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default="{}"
    )


class TenantSealedSecret(Base):
    """Ein versiegeltes Geheimnis eines Kunden (ADR-0024 D3)."""

    __tablename__ = "tenant_sealed_secrets"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), primary_key=True
    )
    name: Mapped[str] = mapped_column(String(64), primary_key=True)
    #: `v1.<base64url>` — öffnen kann es nur die Datenebene dieses Kunden.
    ciphertext: Mapped[str] = mapped_column(Text, nullable=False)
    #: Fingerabdruck des öffentlichen Schlüssels, mit dem versiegelt wurde.
    #: Meldet die Datenebene einen anderen, ist das Geheimnis neu zu setzen.
    key_id: Mapped[str] = mapped_column(String(64), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
    updated_by: Mapped[str | None] = mapped_column(String(320), nullable=True)


class MaintenanceAction(enum.StrEnum):
    #: Die Demoschule `BSP` und alles darunter entfernen.
    demo_purge = "demo_purge"
    #: Aktivitätsprotokoll und Importverlauf leeren (vor der Übergabe).
    audit_reset = "audit_reset"
    #: Lokales Admin-Konto anlegen oder Passwort setzen. Eigener Endpunkt
    #: (POST …/local-admin), nicht über die allgemeine Wartung bestellbar.
    local_admin_setup = "local_admin_setup"


class MaintenanceState(enum.StrEnum):
    requested = "requested"
    done = "done"
    failed = "failed"
    cancelled = "cancelled"


class TenantMaintenanceRequest(Base):
    """Ein Wartungsauftrag für einen Kunden (ADR-0024 D4)."""

    __tablename__ = "tenant_maintenance_requests"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), index=True
    )
    action: Mapped[MaintenanceAction] = mapped_column(
        Enum(MaintenanceAction, name="maintenance_action", native_enum=False, length=32),
        nullable=False,
    )
    state: Mapped[MaintenanceState] = mapped_column(
        Enum(MaintenanceState, name="maintenance_state", native_enum=False, length=16),
        nullable=False,
        default=MaintenanceState.requested,
    )
    reason: Mapped[str] = mapped_column(String(500), nullable=False)
    requested_by: Mapped[str] = mapped_column(String(320), nullable=False)
    requested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    #: Was die Datenebene zurückmeldet: Zählerstände oder ein Fehlercode.
    result: Mapped[dict[str, Any] | None] = mapped_column(JSONB, default=None)
    #: Auftragsparameter für die Datenebene (nur Zeichenketten). Beim lokalen
    #: Admin-Konto steht darin das **versiegelte** Passwort — öffnen kann es
    #: nur die Datenebene. Wird geleert, sobald der Auftrag abgeschlossen ist.
    params: Mapped[dict[str, str] | None] = mapped_column(JSONB, default=None)


class PlatformHeartbeat(Base):
    """Lebenszeichen eines Helfers ausserhalb der Konsole."""

    __tablename__ = "platform_heartbeats"

    name: Mapped[str] = mapped_column(String(64), primary_key=True)
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    detail: Mapped[str | None] = mapped_column(String(2000), default=None)


__all__ = [
    "MaintenanceAction",
    "MaintenanceState",
    "PlatformHeartbeat",
    "TenantMaintenanceRequest",
    "TenantSealedSecret",
    "TenantStatusReport",
]
