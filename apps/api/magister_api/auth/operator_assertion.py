"""Einen Operator-Einlöseschein prüfen (ADR-0019 D2, D3).

Geprüft wird **offline**, gegen einen hinterlegten öffentlichen Schlüssel. Die
Konsole wird dabei nicht gefragt: eine stehende Konsole soll keinen Zugriff auf
einen Kunden verhindern, der gerade ein Problem hat — und ein Problem hat er
meistens dann, wenn etwas steht.

Drei Dinge, die dieses Modul ausdrücklich **nicht** dem Dokument entnimmt:

* **Das Verfahren.** Es steht im Präfix und in diesem Code: Ed25519. Ein
  `alg`-Feld im signierten Dokument lädt dazu ein, dem Dokument zu glauben.
* **Den Mandanten.** Der Aufrufer sagt, für welchen Mandanten die Anfrage
  hereinkam; steht ein anderer im Dokument, ist es eine Ablehnung. Ohne das
  wäre eine Assertion für Kunde A bei Kunde B einlösbar.
* **Die Gültigkeitsdauer.** Auch wenn im Dokument ein Jahr steht, gilt hier
  das Höchstmass dieser Datenebene. Ein Signierschlüssel, der abhanden kommt,
  kann damit kein Dauerticket ausstellen.
"""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519

#: Versions-Präfix **und** Verfahrensangabe (ADR-0019 D2). Derselbe Wert wie in
#: `cockpit_api.services.operator_access`; ein Test hält die beiden zusammen.
ASSERTION_PREFIX = "mgop1"

#: Höchstmass, das diese Datenebene akzeptiert — unabhängig davon, was im
#: Dokument steht. Die Konsole stellt 60 Sekunden aus; zwei Minuten lassen
#: Uhrenversatz und einen langsamen Handgriff zu und sind weit von einem
#: Dauerticket entfernt.
MAX_LIFETIME = timedelta(minutes=2)

#: Zugelassener Uhrenversatz für `iat`. Nur nach vorn: ist die Uhr der Konsole
#: leicht voraus, wäre die Assertion sonst „aus der Zukunft" und würde
#: abgewiesen. Für `exp` gibt es **keine** Toleranz — dort wäre sie eine
#: Verlängerung.
IAT_LEEWAY = timedelta(seconds=30)


class OperatorAssertionError(ValueError):
    """Der Einlöseschein ist nicht gültig. Kein Zugriff."""


@dataclass(frozen=True)
class OperatorAssertion:
    """Der geprüfte Inhalt."""

    jti: UUID
    tenant: str
    operator: str
    reason: str
    ticket: str | None
    issued_at: datetime
    expires_at: datetime


def load_public_key(pem: str) -> ed25519.Ed25519PublicKey:
    if not pem.strip():
        raise OperatorAssertionError(
            "MAGISTER_OPERATOR_PUBLIC_KEY ist nicht gesetzt — kein Operator-Zugriff."
        )
    try:
        key = serialization.load_pem_public_key(pem.encode("utf-8"))
    except Exception as exc:
        raise OperatorAssertionError(f"Öffentlicher Schlüssel ist nicht lesbar: {exc}") from exc
    if not isinstance(key, ed25519.Ed25519PublicKey):
        raise OperatorAssertionError(
            f"Öffentlicher Schlüssel ist {type(key).__name__}, erwartet wird Ed25519."
        )
    return key


def _unb64(value: str, what: str) -> bytes:
    try:
        return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
    except Exception as exc:
        raise OperatorAssertionError(f"{what} ist kein base64url: {exc}") from exc


def _required(payload: dict[str, Any], key: str) -> Any:
    if key not in payload:
        raise OperatorAssertionError(f"Feld '{key}' fehlt im Einlöseschein.")
    return payload[key]


def parse_and_verify(
    raw: str,
    public_key_pem: str,
    *,
    tenant_slug: str,
    now: datetime | None = None,
) -> OperatorAssertion:
    """Den Einlöseschein prüfen und seinen Inhalt zurückgeben.

    Die Reihenfolge ist Absicht: **erst** die Signatur, dann der Inhalt. Was
    vor der Signaturprüfung aus dem Dokument gelesen wird, ist unbeglaubigt —
    und eine Fehlermeldung, die unbeglaubigten Text zitiert, ist ein Weg, über
    den Fremdtext in einen Log kommt.
    """
    key = load_public_key(public_key_pem)
    parts = raw.strip().split(".")
    if len(parts) != 3:
        raise OperatorAssertionError("Einlöseschein hat nicht die Form <präfix>.<inhalt>.<sig>.")
    prefix, body_b64, sig_b64 = parts
    if prefix != ASSERTION_PREFIX:
        raise OperatorAssertionError(
            f"Unbekannte Fassung '{prefix[:16]}'. Diese Datenebene kennt {ASSERTION_PREFIX}."
        )
    body = _unb64(body_b64, "Inhalt")
    signature = _unb64(sig_b64, "Signatur")
    try:
        key.verify(signature, body)
    except InvalidSignature as exc:
        raise OperatorAssertionError("Signatur passt nicht zum hinterlegten Schlüssel.") from exc

    try:
        payload = json.loads(body)
    except ValueError as exc:
        raise OperatorAssertionError(f"Inhalt ist kein JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise OperatorAssertionError("Inhalt ist kein Objekt.")

    try:
        jti = UUID(str(_required(payload, "jti")))
    except ValueError as exc:
        raise OperatorAssertionError("'jti' ist keine UUID.") from exc
    tenant = str(_required(payload, "tenant"))
    if tenant != tenant_slug:
        # Ohne diese Zeile wäre ein Einlöseschein für Kunde A bei Kunde B
        # verwendbar — und die Signatur wäre in beiden Fällen gültig.
        raise OperatorAssertionError(
            f"Einlöseschein gilt für einen anderen Kunden ('{tenant[:32]}')."
        )
    try:
        issued_at = datetime.fromtimestamp(int(_required(payload, "iat")), tz=UTC)
        expires_at = datetime.fromtimestamp(int(_required(payload, "exp")), tz=UTC)
    except (TypeError, ValueError, OSError, OverflowError) as exc:
        raise OperatorAssertionError("'iat' oder 'exp' ist kein Zeitstempel.") from exc

    moment = now or datetime.now(UTC)
    if expires_at <= moment:
        raise OperatorAssertionError("Einlöseschein ist abgelaufen.")
    if issued_at > moment + IAT_LEEWAY:
        raise OperatorAssertionError("Einlöseschein ist aus der Zukunft — Uhren prüfen.")
    if expires_at - issued_at > MAX_LIFETIME:
        raise OperatorAssertionError(
            f"Einlöseschein läuft über {expires_at - issued_at}; diese Datenebene "
            f"akzeptiert höchstens {MAX_LIFETIME}."
        )

    operator = str(_required(payload, "operator")).strip()
    reason = str(_required(payload, "reason")).strip()
    if not operator or not reason:
        raise OperatorAssertionError("Operator und Grund dürfen nicht leer sein.")
    ticket_raw = payload.get("ticket")
    return OperatorAssertion(
        jti=jti,
        tenant=tenant,
        operator=operator,
        reason=reason,
        ticket=None if ticket_raw in (None, "") else str(ticket_raw)[:64],
        issued_at=issued_at,
        expires_at=expires_at,
    )


__all__ = [
    "ASSERTION_PREFIX",
    "IAT_LEEWAY",
    "MAX_LIFETIME",
    "OperatorAssertion",
    "OperatorAssertionError",
    "load_public_key",
    "parse_and_verify",
]
