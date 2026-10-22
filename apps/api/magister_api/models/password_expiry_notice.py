"""Versandprotokoll der Erinnerungen vor dem Passwort-Ablauf.

Eine Zeile je Konto, Ablaufzeitpunkt und Schwelle ("noch 7 Tage"): so geht
jede Erinnerung genau einmal hinaus, auch wenn der Job mehrmals am Tag läuft.
Setzt jemand ein neues Passwort, ändert sich der Ablaufzeitpunkt — die
Erinnerungen beginnen für den neuen Ablauf von vorn.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from magister_api.models.base import Base, utcnow

NOTICE_SENT = "sent"
NOTICE_FAILED = "failed"
#: Kein Postfach: nicht versendet, in der Übersicht sichtbar.
NOTICE_NO_MAIL = "no_mail"


class PasswordExpiryNotice(Base):
    __tablename__ = "password_expiry_notices"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ad_object_guid: Mapped[str] = mapped_column(String(36), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    threshold_days: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(8), nullable=False)
    recipient: Mapped[str | None] = mapped_column(String(320), nullable=True)
    # Nur der Fehlertext des Mailservers, nie Zugangsdaten.
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )

    __table_args__ = (
        UniqueConstraint(
            "ad_object_guid", "expires_at", "threshold_days", name="uq_password_expiry_notice"
        ),
        Index("ix_password_expiry_notices_guid", "ad_object_guid"),
    )
