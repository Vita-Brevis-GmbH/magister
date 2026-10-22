"""Anmeldung und Authentisierung der Connector-Agenten (ADR-0014).

Zwei Faktoren, gegen **dieselbe** Agent-Zeile geprüft:

1. Das Client-Zertifikat: der Reverse Proxy hat die Kette gegen die
   Plattform-CA verifiziert, die Anwendung rechnet den **SPKI-Fingerprint**
   nach und vergleicht ihn mit der Zeile. Die Kette allein genügt nicht —
   sonst käme der Agent von Kunde A auf den Kanal von Kunde B.
2. Der API-Key, hier nur als argon2id-Hash. Wer die Konsolen-Datenbank liest,
   bekommt damit keinen Kanal.

Beides muss auf dieselbe Zeile zeigen. Ein Zertifikat von Kunde A mit dem
API-Key von Kunde B ist eine Ablehnung, nicht ein Treffer.

Zur Reihenfolge der Prüfungen: erst der Fingerprint (er wählt die Zeile), dann
der API-Key (er bestätigt sie). Umgekehrt müsste man den Key gegen alle Zeilen
prüfen — jede argon2id-Prüfung kostet absichtlich Zeit, das wäre ein
Selbst-DoS.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from argon2 import PasswordHasher
from argon2.exceptions import VerificationError, VerifyMismatchError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from cockpit_api.models import (
    AgentStatus,
    ConnectorAgent,
    ConnectorEnrollment,
    Tenant,
    TenantStatus,
)

logger = logging.getLogger(__name__)

_hasher = PasswordHasher()

#: Gültigkeit eines Einmal-Tokens. Kurz, weil es im Download-Paket reist.
ENROLLMENT_TTL = timedelta(hours=24)

#: Länge der erzeugten Geheimnisse (Bytes vor base64).
SECRET_BYTES = 32

#: Nach dieser Stille gilt ein Agent als abgehängt. Der Kunde bekommt dann das
#: bestehende Wartungsbanner, keinen Fehler.
STALE_AFTER = timedelta(minutes=5)

#: Wie lange der vorherige SPKI-Fingerprint nach einer Erneuerung zusätzlich
#: gilt (ADR-0014).
#:
#: Der Übergang ist nötig, weil die Erneuerung sonst ein Vabanquespiel wäre:
#: die Plattform schreibt den neuen Fingerprint, die Antwort geht auf dem
#: Rückweg verloren (abgebrochene Verbindung, Proxy-Zeitüberschreitung,
#: Neustart des Agenten in genau diesem Moment), und der Agent klopft weiter
#: mit dem alten Schlüssel an — auf eine Zeile, die ihn nicht mehr kennt. Er
#: wäre ausgesperrt, und zwar endgültig: ein neues Einmal-Token kann nur ein
#: Mensch ausstellen, und beim Kunden sitzt niemand daneben.
#:
#: Sieben Tage, weil der Agent 30 Tage vor Ablauf erneuert und einen
#: gescheiterten Versuch danach stündlich wiederholt. Länger wäre kein
#: Übergang mehr, sondern ein zweiter gültiger Schlüssel.
ROTATION_GRACE = timedelta(days=7)


class ConnectorAuthError(RuntimeError):
    """Die Anfrage gehört zu keinem brauchbaren Agenten.

    Absichtlich ohne Unterscheidung nach aussen: ob Fingerprint unbekannt,
    API-Key falsch oder Agent widerrufen ist, erfährt der Anrufer nicht. Der
    Grund steht im Log.
    """


class EnrollmentError(RuntimeError):
    """Das Einmal-Token ist unbrauchbar."""


@dataclass(frozen=True, slots=True)
class AgentSecrets:
    """Geheimnisse, die genau einmal herausgehen."""

    api_key: str
    result_hmac_key: str


def new_secret() -> str:
    return secrets.token_urlsafe(SECRET_BYTES)


def hash_token(token: str) -> str:
    """SHA-256 für das Einmal-Token.

    Kein argon2 hier: das Token ist 32 Byte Zufall aus ``secrets``, kein
    Menschenpasswort. Gegen Raten hilft die Entropie, und der Nachschlag muss
    ein Index-Treffer sein — bei argon2 könnte man nicht nach dem Hash suchen.
    """
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def hash_api_key(api_key: str) -> str:
    return _hasher.hash(api_key)


def verify_api_key(stored_hash: str, api_key: str) -> bool:
    try:
        _hasher.verify(stored_hash, api_key)
    except (VerifyMismatchError, VerificationError):
        return False
    return True


def canonical_result_body(*, ok: bool, result: dict[str, Any] | None, error: str | None) -> bytes:
    """Kanonische Form des Ergebnisses für die HMAC.

    ``sort_keys`` und feste Trennzeichen, damit Agent und Plattform garantiert
    dieselben Bytes hashen. Ohne das wäre die Signatur von der Reihenfolge
    abhängig, in der zwei verschiedene JSON-Bibliotheken Schlüssel ausgeben —
    ein Fehler, der nur manchmal auftritt und deshalb besonders teuer ist.
    """
    return json.dumps(
        {"ok": ok, "result": result, "error": error},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def sign_result(hmac_key: str, job_id: str, body: bytes) -> str:
    """HMAC über Auftrags-Id und Ergebniskörper.

    Die Auftrags-Id gehört mit hinein: sonst liesse sich ein gültig
    signiertes Ergebnis von einem Auftrag auf einen anderen umhängen.
    """
    mac = hmac.new(hmac_key.encode("utf-8"), digestmod=hashlib.sha256)
    mac.update(job_id.encode("ascii"))
    mac.update(b"\x00")
    mac.update(body)
    return mac.hexdigest()


def verify_result_signature(hmac_key: str, job_id: str, body: bytes, provided: str) -> bool:
    expected = sign_result(hmac_key, job_id, body)
    # compare_digest über die hex-Strings: beide sind ASCII, also kein
    # TypeError-Risiko wie bei beliebiger Eingabe.
    return secrets.compare_digest(expected, provided.strip().lower())


async def create_enrollment(
    session: AsyncSession, tenant: Tenant, *, agent_name: str, issued_by: str
) -> tuple[ConnectorEnrollment, str]:
    """Einmal-Token anlegen. Der Klartext kommt genau einmal zurück."""
    token = new_secret()
    row = ConnectorEnrollment(
        tenant_id=tenant.id,
        token_hash=hash_token(token),
        agent_name=agent_name,
        expires_at=datetime.now(UTC) + ENROLLMENT_TTL,
        issued_by=issued_by,
    )
    session.add(row)
    await session.flush()
    logger.info(
        "Einmal-Token für Kunde %s, Agent %s ausgestellt (gültig bis %s)",
        tenant.slug,
        agent_name,
        row.expires_at.isoformat(),
    )
    return row, token


async def redeem_enrollment(session: AsyncSession, token: str) -> ConnectorEnrollment:
    """Token einlösen. Genau einmal, und nur solange es gilt."""
    stmt = select(ConnectorEnrollment).where(ConnectorEnrollment.token_hash == hash_token(token))
    row = (await session.execute(stmt)).scalar_one_or_none()
    if row is None:
        raise EnrollmentError("Unbekanntes oder bereits verbrauchtes Token.")
    if row.redeemed_at is not None:
        # Ein zweiter Versuch mit demselben Token heisst: entweder ein
        # doppelter Lauf des Installers, oder jemand hat das Paket abgefangen.
        # Beides gehört in das Log, und beides wird abgelehnt.
        logger.warning(
            "Einmal-Token für Agent %s wurde erneut vorgelegt (erstmals eingelöst am %s)",
            row.agent_name,
            row.redeemed_at.isoformat(),
        )
        raise EnrollmentError("Token wurde bereits eingelöst.")
    if row.expires_at <= datetime.now(UTC):
        raise EnrollmentError("Token ist abgelaufen.")
    return row


async def authenticate_agent(
    session: AsyncSession, *, spki_sha256: str, api_key: str
) -> tuple[ConnectorAgent, Tenant]:
    """Agent und Kunde zu einer Anfrage bestimmen — oder ablehnen.

    Reihenfolge: Fingerprint wählt die Zeile, API-Key bestätigt sie, Zustand
    des Agenten und des Kunden entscheiden über die Bedienung.
    """
    normalized = spki_sha256.strip().lower()
    now = datetime.now(UTC)
    agent = (
        await session.execute(
            select(ConnectorAgent).where(ConnectorAgent.spki_sha256 == normalized)
        )
    ).scalar_one_or_none()
    via_previous = False
    if agent is None:
        # Zweiter Versuch über den vorherigen Fingerprint: eine Erneuerung, bei
        # der die Antwort verloren ging. Ohne diesen Zweig wäre der Agent
        # ausgesperrt (siehe ROTATION_GRACE).
        agent = (
            await session.execute(
                select(ConnectorAgent).where(ConnectorAgent.previous_spki_sha256 == normalized)
            )
        ).scalar_one_or_none()
        if agent is not None:
            rotated = agent.spki_rotated_at
            if rotated is None or now - rotated > ROTATION_GRACE:
                # Übergangsfenster abgelaufen. Der alte Schlüssel ist damit
                # endgültig ungültig — sonst wäre er ein zweiter gültiger.
                logger.warning(
                    "Agent %s meldet sich mit dem alten Fingerprint, das "
                    "Übergangsfenster ist aber abgelaufen.",
                    agent.id,
                )
                raise ConnectorAuthError("Übergangsfenster abgelaufen")
            via_previous = True
            logger.info(
                "Agent %s meldet sich noch mit dem alten Fingerprint. Die "
                "Erneuerung ist bei ihm nicht angekommen; er wird sie "
                "wiederholen.",
                agent.id,
            )
    if agent is None:
        logger.warning("Connector-Anfrage mit unbekanntem SPKI-Fingerprint abgewiesen")
        raise ConnectorAuthError("unbekannter Agent")
    if not agent.is_usable:
        # Der Widerruf ist ein Datenbank-Flag und wird bei JEDER Anfrage
        # geprüft — es gibt keine CRL, die erst morgen aktuell wäre.
        logger.warning("Anfrage eines widerrufenen Agenten %s abgewiesen", agent.id)
        raise ConnectorAuthError("Agent widerrufen")
    if not verify_api_key(agent.api_key_hash, api_key):
        logger.warning("Anfrage von Agent %s mit falschem API-Key abgewiesen", agent.id)
        raise ConnectorAuthError("falscher API-Key")

    tenant = await session.get(Tenant, agent.tenant_id)
    if tenant is None:
        raise ConnectorAuthError("Agent ohne Kunden")
    if tenant.status is not TenantStatus.active:
        # Ein gesperrter Kunde soll auch über den Connector nichts bewegen.
        logger.warning(
            "Anfrage von Agent %s abgewiesen: Kunde %s ist %s",
            agent.id,
            tenant.slug,
            tenant.status.value,
        )
        raise ConnectorAuthError("Kunde nicht aktiv")

    agent.last_seen_at = now
    if agent.status is not AgentStatus.online:
        agent.status = AgentStatus.online
    if not via_previous and agent.previous_spki_sha256 is not None:
        # Der Agent benutzt den NEUEN Schlüssel — die Erneuerung ist bei ihm
        # angekommen. Damit ist der alte nicht mehr nötig, und je kürzer er
        # gilt, desto besser.
        logger.info("Erneuerung von Agent %s bestätigt, alter Fingerprint verworfen", agent.id)
        agent.previous_spki_sha256 = None
        agent.spki_rotated_at = None
    return agent, tenant


def agent_is_stale(agent: ConnectorAgent, *, now: datetime | None = None) -> bool:
    if agent.last_seen_at is None:
        return True
    return (now or datetime.now(UTC)) - agent.last_seen_at > STALE_AFTER
