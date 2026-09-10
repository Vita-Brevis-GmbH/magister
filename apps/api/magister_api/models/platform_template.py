"""Vom Betreiber gelieferte Vorlagen im Kundenschema (ADR-0018 D2).

Eine **eigene** Tabelle, getrennt von `document_templates`. Der naheliegende
Entwurf wäre eine Tabelle mit `origin ∈ {local, platform}` gewesen; er
scheitert daran, dass der Abgleich dann entscheiden müsste, welche der beiden
Fassungen er überschreibt — und jede Antwort ist irgendwann die falsche.

So kann er die Frage nicht stellen: er schreibt ausschliesslich hier. Dass die
eigene Fassung des Kunden unangetastet bleibt, ist damit keine Sorgfalt,
sondern Bauart.

Kein `school_id`: eine Plattformvorlage gilt für den ganzen Mandanten. Der
Betreiber kennt die Standorte seiner Kunden nicht und soll sie nicht kennen
müssen.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from magister_api.models.base import Base, utcnow


class PlatformDocumentTemplate(Base):
    __tablename__ = "platform_document_templates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    key: Mapped[str] = mapped_column(String(64), nullable=False)
    language: Mapped[str] = mapped_column(String(8), nullable=False)
    subject: Mapped[str | None] = mapped_column(String(512), nullable=True)
    body_html: Mapped[str] = mapped_column(Text, nullable=False, default="")

    #: `False` heisst: diese Fassung gilt, auch wenn der Kunde eine eigene hat
    #: (ADR-0018 D3). Seine bleibt liegen und wird nicht gelöscht — eine Sperre
    #: kann zurückgenommen werden, und dann soll sein Text wieder da sein.
    may_override: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )

    #: Die Fassungsnummer der Konsole. Wird gegen
    #: `document_templates.platform_version_ack` verglichen; daraus entsteht
    #: der Hinweis „neue globale Fassung verfügbar" (ADR-0018 D4).
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    #: Wann der Abgleich diese Fassung hereingeholt hat. Nicht Zierrat: wer
    #: sich fragt, ob eine Änderung in der Konsole schon angekommen ist,
    #: bekommt hier die Antwort ohne einen Blick in den Log.
    delivered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )

    __table_args__ = (
        Index("ix_platform_document_templates_key_lang", "key", "language", unique=True),
        CheckConstraint("version >= 1", name="ck_platform_document_templates_version"),
    )


__all__ = ["PlatformDocumentTemplate"]
