"""Eingelöste Operator-Zugriffe im Kundenschema (ADR-0019 D4).

Diese Tabelle leistet **zwei** Dinge, und dass es eine ist, ist der Entscheid:

* **Einmal-Einlösung.** Der Primärschlüssel auf `jti` weist die zweite
  Einlösung ab — durch Postgres, auch bei zwei Anfragen in derselben
  Millisekunde.
* **Die Zugriffsliste für den Kunden.** Dieselben Zeilen sind die Antwort auf
  „wann war Vita Brevis bei uns drin, und warum".

Ein separater Nonce-Speicher mit Verfall wäre die üblichere Bauart und hier
schlechter: verfallene Einträge würden gelöscht, und damit wäre eine alte
Assertion irgendwann **wieder** einlösbar.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Index, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from magister_api.models.base import Base, utcnow


class OperatorAccess(Base):
    __tablename__ = "operator_accesses"

    #: Der `jti` der eingelösten Assertion. Kein eigener Zähler: derselbe Wert
    #: steht im Protokoll der Konsole, und damit lassen sich die zwei Zeilen
    #: ohne Zuordnungsarbeit verbinden.
    jti: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)

    operator_upn: Mapped[str] = mapped_column(String(320), nullable=False)
    #: Der Grund, wie er in der signierten Assertion stand. Er kann auf dem
    #: Weg nicht geändert werden — auch nicht von dieser Datenebene.
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    ticket: Mapped[str | None] = mapped_column(String(64), nullable=True)

    #: **Nur der Anfang** der Session-Id. Der vollständige Wert ist das Cookie
    #: und damit ein Zugangsmittel; ihn in einer Tabelle zu führen, die
    #: absichtlich nie aufgeräumt wird, wäre ein Passwortspeicher mit
    #: Leserechten für die halbe Anwendung.
    session_ref: Mapped[str] = mapped_column(String(16), nullable=False)

    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    #: Ablauf der **Sitzung** (60 Minuten), nicht der Assertion.
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    #: Gesetzt, wenn der Operator sich abgemeldet hat. `None` heisst „läuft
    #: noch oder ist abgelaufen" — welches von beidem, entscheidet
    #: `expires_at`. Zwei Felder statt eines Zustands: ein abgelaufener
    #: Zugriff und ein beendeter sind für den Kunden nicht dasselbe.
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    ip: Mapped[str | None] = mapped_column(String(64), nullable=True)

    __table_args__ = (Index("ix_operator_accesses_started", "started_at"),)


__all__ = ["OperatorAccess"]
