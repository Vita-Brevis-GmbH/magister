"""Connector-Agenten, Anmeldung und Auftragswarteschlange (ADR-0014).

Der Agent telefoniert nach Hause: die Plattform baut **nie** eine Verbindung
ins Kundennetz auf, LDAP verlässt das Kundennetz nicht. Was hier liegt, ist die
Gegenseite dieses Anrufs.

Zwei Faktoren, beide gegen **dieselbe** Agent-Zeile geprüft:

1. Ein Client-Zertifikat aus der Plattform-CA, dessen **SPKI-Fingerprint** mit
   dem hier gespeicherten übereinstimmt. Die Kette allein genügt nicht — sonst
   käme jeder Agent auf den Kanal jedes Kunden.
2. Ein API-Key, hier nur als **argon2id-Hash**. Wer die Konsolen-Datenbank
   liest, bekommt damit keinen Kanal.

Der private Schlüssel des Agenten entsteht **auf dem Agenten** und verlässt ihn
nie. Die Plattform sieht nur den CSR. Das Download-Paket enthält deshalb kein
Geheimnis — nur Installer, CA-Bundle und ein Einmal-Token.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Enum, ForeignKey, Index, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from cockpit_api.models.base import Base


class AgentStatus(enum.StrEnum):
    """Zustand eines Agenten.

    ``enrolled`` heisst: Zertifikat ausgestellt, aber noch kein Kontakt.
    ``revoked`` ist endgültig — es gibt keine CRL, der Widerruf ist genau
    dieses Flag und wird bei **jeder** Anfrage geprüft (ADR-0014 §6).
    """

    enrolled = "enrolled"
    online = "online"
    stale = "stale"
    revoked = "revoked"


class JobState(enum.StrEnum):
    queued = "queued"
    claimed = "claimed"
    done = "done"
    failed = "failed"
    expired = "expired"


class ConnectorAgent(Base):
    __tablename__ = "connector_agents"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(200))
    status: Mapped[AgentStatus] = mapped_column(
        Enum(AgentStatus, name="connector_agent_status"), default=AgentStatus.enrolled
    )
    #: SHA-256 über den DER-kodierten öffentlichen Schlüssel (SubjectPublicKeyInfo),
    #: hex. Bindet den Kanal an genau dieses Schlüsselpaar — und übersteht eine
    #: Zertifikatserneuerung mit demselben Schlüssel, anders als ein Fingerprint
    #: über das Zertifikat.
    spki_sha256: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    #: Seriennummer des ausgestellten Zertifikats, hex. Fürs Protokoll.
    certificate_serial: Mapped[str] = mapped_column(String(64))
    certificate_not_after: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    #: argon2id-Hash des API-Keys. Nie der Key selbst.
    api_key_hash: Mapped[str] = mapped_column(String(255))
    #: Gemeinsames Geheimnis für die HMAC über Ergebnisse. Ebenfalls nur als
    #: Hash? Nein: die Plattform muss die HMAC nachrechnen, braucht also den
    #: Wert. Deshalb getrennt vom API-Key — ein Leck der Datenbank gibt einem
    #: Angreifer die Möglichkeit, Ergebnisse zu fälschen, aber keinen Kanal.
    result_hmac_key: Mapped[str] = mapped_column(String(128))
    agent_version: Mapped[str | None] = mapped_column(String(64), default=None)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    revoked_reason: Mapped[str | None] = mapped_column(String(500), default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    @property
    def is_usable(self) -> bool:
        return self.status is not AgentStatus.revoked and self.revoked_at is None


class ConnectorEnrollment(Base):
    """Einmal-Token für die Anmeldung eines Agenten.

    24 Stunden gültig, genau einmal einlösbar. Im Download-Paket liegt nur
    dieses Token — kein Schlüssel, kein API-Key. Wer das Paket abfängt, kann
    einen Agenten anmelden, solange das Token gilt; deshalb die kurze Frist,
    die Einmal-Einlösung und der sichtbare Fingerprint danach in der Konsole,
    an dem der Betreiber merkt, wenn sich ein Fremder angemeldet hat.
    """

    __tablename__ = "connector_enrollments"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), index=True
    )
    #: SHA-256 des Tokens, hex. Der Klartext wird einmal angezeigt.
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    agent_name: Mapped[str] = mapped_column(String(200))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    redeemed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    redeemed_agent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("connector_agents.id", ondelete="SET NULL"), default=None
    )
    issued_by: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ConnectorJob(Base):
    """Ein Auftrag an den Agenten.

    ``method`` muss in der Allowlist stehen — es gibt keinen Weg, beliebiges
    LDAP, PowerShell oder ein Skript zu schicken. Die Prüfung passiert
    plattformseitig **und** im Agenten; die hier ist die erste.

    ``payload`` kann ein Passwort enthalten (``modify_password``). Solche
    Nutzlasten werden nach Abschluss sofort gelöscht — deshalb
    ``payload_purged_at``, damit man einem leeren Feld ansieht, dass es
    absichtlich leer ist und nicht nie gefüllt war.
    """

    __tablename__ = "connector_jobs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), index=True
    )
    agent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("connector_agents.id", ondelete="SET NULL"), default=None
    )
    method: Mapped[str] = mapped_column(String(64))
    payload: Mapped[dict[str, Any] | None] = mapped_column(JSONB, default=None)
    payload_purged_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )
    state: Mapped[JobState] = mapped_column(
        Enum(JobState, name="connector_job_state"), default=JobState.queued
    )
    result: Mapped[dict[str, Any] | None] = mapped_column(JSONB, default=None)
    error: Mapped[str | None] = mapped_column(String(2000), default=None)
    #: Nach dieser Zeit gilt der Auftrag als verfallen. Ein Agent, der zehn
    #: Minuten weg war, soll ein Passwort nicht mehr setzen — der Anwender hat
    #: längst einen Fehler gesehen und es erneut versucht.
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        # Der Abholpfad: offene Aufträge eines Kunden in Reihenfolge.
        Index("ix_connector_jobs_queue", "tenant_id", "state", "created_at"),
    )
