"""Mandanten-Registry in der Konsolen-Datenbank (ADR-0013 D1, D2).

Die Konsole ist die Autorenstelle für die Registry. Sie hält **keine
Personendaten der Kunden** — nur, wo ein Kunde liegt und in welchem Zustand er
ist.

Warum ``dsn_ref`` und nicht der DSN: der DSN trägt das Passwort der
Mandantenrolle. Ein Geheimnis in der Konsolen-Datenbank wäre eines mehr an
einer Stelle, die schon das höchstwertige Ziel im System ist. Die Konsole
speichert deshalb nur einen **Verweis**; das Passwort selbst löst die
Datenebene aus ihrem eigenen Geheimnisspeicher auf. Der Bereitstellungs-Auftrag
zeigt es genau einmal an und speichert es nirgends.
"""

from __future__ import annotations

import enum
import re
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Index, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from cockpit_api.models.base import Base, enum_column

#: Dasselbe Muster wie in der Datenebene
#: (``magister_api.tenancy.registry.SLUG_PATTERN``). Aus dem Slug werden
#: Schema- und Rollenname gebildet, und die gehen unquotiert in SQL — deshalb
#: eng, und deshalb an beiden Enden geprüft. Ein Test hält die beiden Muster
#: zusammen.
SLUG_PATTERN = re.compile(r"^[a-z][a-z0-9_]{1,30}$")


class TenantStatus(enum.StrEnum):
    """Lebenszyklus. Nur ``active`` wird von der Datenebene bedient."""

    provisioning = "provisioning"
    active = "active"
    suspended = "suspended"
    offboarding = "offboarding"


class TenantProfile(enum.StrEnum):
    """Bestimmt das Standard-Set an Rollen und Vorlagen (ADR-0013 D4)."""

    school = "school"
    company = "company"
    neutral = "neutral"


class IsolationMode(enum.StrEnum):
    """Wie weit ein Kunde getrennt liegt.

    Alle drei sind derselbe Code-Pfad und unterscheiden sich nur im
    Registry-Eintrag: ``schema`` teilt die Datenbank, ``database`` bekommt eine
    eigene, ``cluster`` einen eigenen Server. Ein Umzug ist ein neuer
    ``dsn_ref``, kein Umbau.
    """

    schema_only = "schema"
    database = "database"
    cluster = "cluster"


class Tenant(Base):
    __tablename__ = "tenants"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    slug: Mapped[str] = mapped_column(String(31), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(200))
    customer_no: Mapped[str | None] = mapped_column(String(64), default=None)
    hostname: Mapped[str] = mapped_column(String(253), unique=True, index=True)
    status: Mapped[TenantStatus] = mapped_column(
        enum_column(TenantStatus, name="tenant_status"), default=TenantStatus.provisioning
    )
    profile: Mapped[TenantProfile] = mapped_column(
        enum_column(TenantProfile, name="tenant_profile"), default=TenantProfile.school
    )
    isolation_mode: Mapped[IsolationMode] = mapped_column(
        enum_column(IsolationMode, name="tenant_isolation_mode"), default=IsolationMode.schema_only
    )
    #: Verweis auf den DSN im Geheimnisspeicher der Datenebene, NICHT der DSN.
    dsn_ref: Mapped[str] = mapped_column(String(64))
    schema_name: Mapped[str] = mapped_column(String(63))
    db_role: Mapped[str] = mapped_column(String(63))
    #: Alembic-Revision, auf der das Kundenschema steht. Weicht sie von der
    #: Kopf-Version des Codes ab, bedient die Datenebene diesen Kunden mit
    #: 503 Wartung (ADR-0013 D7).
    schema_version: Mapped[str | None] = mapped_column(String(64), default=None)
    #: Id des Kundenschlüssels (ADR-0016 D2, D8). Ein **Verweis**, nie der
    #: Schlüssel selbst: der liegt in der Umgebung des Anwendungsservers. Jede
    #: Sicherung vermerkt diese Id, und wer wiederherstellt, sucht damit den
    #: passenden Schlüssel — steht bei allen Kunden derselbe Wert, ist der
    #: Vermerk wertlos.
    audit_key_id: Mapped[str | None] = mapped_column(String(64), default=None)
    suspended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    #: Der Grund ist für den Kunden sichtbar — Sperren ohne Begründung ist
    #: der Anfang von Willkür.
    suspended_reason: Mapped[str | None] = mapped_column(String(500), default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        # Schema und Rolle sind innerhalb einer Ablage eindeutig. Die
        # Eindeutigkeit über alle Ablagen hinweg ist strenger als nötig (zwei
        # Cluster dürften beide t_default haben), aber sie kostet nichts und
        # verhindert die Verwechslung, die beim Debuggen Stunden frisst.
        Index("ix_tenants_schema_name", "schema_name", unique=True),
        Index("ix_tenants_db_role", "db_role", unique=True),
    )
