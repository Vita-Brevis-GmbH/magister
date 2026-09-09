"""Offboarding eines Kunden (ADR-0016 D8).

Der Ablauf hat Fristen, und die Fristen sind Vertragssache — also stehen sie
in einer Zeile und nicht in einem Runbook. Fünf Zustände, in dieser Reihenfolge:

``requested``      Kündigung erfasst, Karenzzeit läuft.
``export_ready``   Der Export ist erstellt und dem Kunden zugestellt.
``dropped``        Schema und Datenbankrolle sind gelöscht.
``shredded``       Der Kundenschlüssel ist vernichtet (Crypto-Shredding).
``purged``         Die Aufbewahrungsfrist der Sicherungen ist abgelaufen.

Warum ``dropped`` und ``shredded`` **getrennt** sind, obwohl sie im ADR in
einem Satz stehen: das Löschen von Schema und Rolle kann die Konsole selbst
tun und nachweisen — sie führt das SQL aus und kann danach prüfen, dass beides
weg ist. Das Vernichten des Kundenschlüssels kann sie **nicht**: der Schlüssel
liegt in der Umgebung des Anwendungsservers, und dorthin reicht die Konsole
nicht. Sie kann es nur festhalten, nachdem ein Mensch es getan und bestätigt
hat. Zwei verschiedene Grade von Gewissheit gehören nicht in dasselbe Feld.

Und ``purged`` ist keine Handlung, sondern ein **Datum**: zehn Tage nach dem
Shredding (Entscheid E14) sind auch die Sicherungen auf dem Share und im
Tages-Backup abgelaufen. Erst dann ist die Zusage an den Kunden erfüllt. Wer
„vollständig gelöscht" früher meldet, sagt etwas Unwahres.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from cockpit_api.models.base import Base, enum_column


class OffboardingState(enum.StrEnum):
    requested = "requested"
    export_ready = "export_ready"
    dropped = "dropped"
    shredded = "shredded"
    purged = "purged"
    #: Kündigung zurückgezogen. Nur solange nichts gelöscht wurde — nach
    #: ``dropped`` gibt es keinen Weg zurück, und ein Zustand, der das
    #: verspricht, wäre eine Lüge.
    aborted = "aborted"


class TenantOffboarding(Base):
    """Eine Zeile je Kunde. Offboarding geschieht einmal."""

    __tablename__ = "tenant_offboarding"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), primary_key=True
    )
    state: Mapped[OffboardingState] = mapped_column(
        enum_column(OffboardingState, name="offboarding_state"),
        default=OffboardingState.requested,
    )
    #: Kündigung, Vertragsnummer, Ticket. Pflicht: ein Offboarding ohne
    #: benannten Anlass ist entweder ein Versehen oder ein Zugriff.
    reason: Mapped[str] = mapped_column(String(500))
    requested_by: Mapped[str] = mapped_column(String(200))
    requested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    #: Vertragswert, Vorgabe 30 Tage (ADR-0016 D8).
    grace_days: Mapped[int] = mapped_column(Integer, default=30)
    #: Vor diesem Zeitpunkt wird nichts gelöscht. Der Kunde soll seine Daten
    #: holen können, auch wenn die zuständige Person Ferien hat.
    grace_until: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    #: Letzter Stand vor dem Löschen, Art ``offboarding``.
    final_backup_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenant_backups.id", ondelete="SET NULL"), default=None
    )
    export_job_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("export_jobs.id", ondelete="SET NULL"), default=None
    )
    #: Wann der Kunde den Export erhalten hat. Vor diesem Zeitpunkt wird
    #: nichts gelöscht — die Reihenfolge ist der Kern der Zusage.
    export_delivered_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )

    dropped_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    #: Wer gelöscht hat und wer freigegeben hat — zwei Personen, wie beim
    #: Umschalten einer Wiederherstellung (ADR-0016 D5). Ein ``DROP SCHEMA``
    #: auf ein Kundenschema ist die unwiderruflichste Operation im System.
    dropped_by: Mapped[str | None] = mapped_column(String(200), default=None)
    approved_by: Mapped[str | None] = mapped_column(String(200), default=None)

    #: Bestätigung eines Menschen, dass der Kundenschlüssel vernichtet ist.
    #: Die Konsole kann das nicht überprüfen — sie hält es fest, und diese
    #: Grenze steht auch im Modul-Docstring, damit sie nicht mit einer
    #: Prüfung verwechselt wird.
    key_destroyed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    key_destroyed_by: Mapped[str | None] = mapped_column(String(200), default=None)
    #: Id des vernichteten Schlüssels, aus ``tenants.audit_key_id`` kopiert.
    #: Nach dem Offboarding ist die Kundenzeile eventuell weg; der Nachweis,
    #: *welcher* Schlüssel vernichtet wurde, soll bleiben.
    key_id: Mapped[str | None] = mapped_column(String(64), default=None)

    #: Ab wann auch die Sicherungen abgelaufen sind. ``key_destroyed_at`` plus
    #: Aufbewahrungsfrist. Das ist das Datum, das dem Kunden zugesagt wird.
    purge_due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    purged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)

    aborted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    aborted_reason: Mapped[str | None] = mapped_column(String(500), default=None)

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


__all__ = ["OffboardingState", "TenantOffboarding"]
