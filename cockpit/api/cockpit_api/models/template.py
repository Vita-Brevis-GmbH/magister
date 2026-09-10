"""Globale Vorlagen der Plattform (ADR-0018).

Was hier steht, ist der Text, den **der Betreiber** pflegt und alle
zutreffenden Kunden bekommen. Er reist über denselben Kanal wie die
Einstellungen: die Datenebene holt ihn im Soll-Zustand ab (ADR-0018 D1).

Was hier **nicht** steht, ist der Text eines Kunden. Der liegt in dessen
Schema, in einer anderen Tabelle, und wird von hier aus nie berührt
(ADR-0018 D2). Diese Trennung ist der Grund, aus dem ein Rollout einen
gewachsenen Elternbrief nicht überfahren kann.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from cockpit_api.models.base import Base, enum_column
from cockpit_api.models.tenant import TenantProfile


class TemplateAudience(enum.StrEnum):
    """An wen sich eine Vorlage richtet (ADR-0018 D5).

    Aufgelöst wird das in der Konsole; im Soll-Zustand steht nur das Ergebnis.
    Der Kunde erfährt nicht, dass es andere Zielgruppen gibt.
    """

    all = "all"
    profile = "profile"
    selection = "selection"


class PlatformTemplate(Base):
    __tablename__ = "platform_templates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    #: Vorlagen-Schlüssel der Datenebene (`enrollment`, `class_change`,
    #: `password_handout`). Bewusst kein Enum: die Liste gehört der
    #: Datenebene, und ein neuer Schlüssel dort wäre sonst eine Migration
    #: hier. Ob der Schlüssel bekannt ist, prüft der Dienst.
    key: Mapped[str] = mapped_column(String(64), nullable=False)
    language: Mapped[str] = mapped_column(String(8), nullable=False)

    subject: Mapped[str | None] = mapped_column(String(512), nullable=True)
    body_html: Mapped[str] = mapped_column(Text, nullable=False, default="")

    #: Darf der Kunde eine eigene Fassung darüberlegen? `False` heisst: die
    #: Plattformfassung gilt, die eigene bleibt liegen (ADR-0018 D3). Sie wird
    #: **nicht** gelöscht — eine Sperre kann zurückgenommen werden.
    may_override: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )

    #: Steigt nur bei einer **inhaltlichen** Änderung (Betreff, Rumpf,
    #: Sperre). Eine Änderung der Zielgruppe ändert, *wer* die Vorlage
    #: bekommt, nicht *was* sie sagt (ADR-0018 D4). Eine Zahl und kein Hash:
    #: „neuer als quittiert" ist ein Vergleich, und ein Hash ist ungleich,
    #: aber nicht grösser.
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")

    audience: Mapped[TemplateAudience] = mapped_column(
        enum_column(TemplateAudience, name="template_audience"),
        nullable=False,
        default=TemplateAudience.all,
    )
    #: Nur bei `audience = profile` gesetzt; die Prüfung steht als
    #: CheckConstraint in der Datenbank, damit sie auch für ein `psql` gilt.
    audience_profile: Mapped[TenantProfile | None] = mapped_column(
        enum_column(TenantProfile, name="tenant_profile"), nullable=True
    )

    #: Ausgeschaltet heisst: wird nicht ausgeliefert. Beim nächsten Abgleich
    #: verschwindet sie damit aus dem Kundenschema (ADR-0018 D6) — die eigene
    #: Fassung des Kunden bleibt.
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
    updated_by: Mapped[str | None] = mapped_column(String(320), nullable=True)

    __table_args__ = (
        Index("ix_platform_templates_key_lang", "key", "language", unique=True),
        CheckConstraint(
            "(audience = 'profile') = (audience_profile IS NOT NULL)",
            name="ck_platform_templates_profile",
        ),
        CheckConstraint("version >= 1", name="ck_platform_templates_version"),
    )


class PlatformTemplateTenant(Base):
    """Die ausgewählten Kunden bei `audience = selection`.

    Eine eigene Tabelle und keine Liste von Ids in einem JSONB: hier steht ein
    Fremdschlüssel auf `tenants`, und ein gekündigter Kunde verschwindet damit
    aus der Auswahl, statt als Id einer nicht mehr existierenden Zeile
    liegenzubleiben.
    """

    __tablename__ = "platform_template_tenants"

    platform_template_id: Mapped[int] = mapped_column(
        ForeignKey("platform_templates.id", ondelete="CASCADE"), primary_key=True
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        primary_key=True,
        index=True,
    )


__all__ = ["PlatformTemplate", "PlatformTemplateTenant", "TemplateAudience"]
