"""HMAC über Auftragsergebnisse (ADR-0014).

Wörtlich dieselbe Berechnung wie in der Konsole
(``cockpit_api/services/connector.py``). Bewusst zweimal geschrieben und nicht
geteilt: der Agent ist ein eigenständiges Paket beim Kunden und soll nicht die
Konsole importieren. Ein Test hält die beiden Implementierungen zusammen,
indem er dieselben Eingaben durch beide schickt.

Die Signatur beweist nicht die Identität — das tun Client-Zertifikat und
API-Key. Sie beweist die **Unversehrtheit**: ein Zwischenglied, das TLS
terminiert, kann ein „Passwort gesetzt" nicht in ein „nein" verwandeln, ohne
dass es auffällt.

Die Auftrags-Id gehört in die Signatur, sonst liesse sich ein gültig signiertes
Ergebnis von einem Auftrag auf einen anderen umhängen.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any


def canonical_result_body(*, ok: bool, result: Any, error: str | None) -> bytes:
    """Kanonische Bytes des Ergebnisses.

    ``sort_keys`` und feste Trennzeichen, damit Agent und Plattform garantiert
    dieselben Bytes hashen. Ohne das hinge die Signatur von der Reihenfolge ab,
    in der zwei JSON-Bibliotheken Schlüssel ausgeben — ein Fehler, der nur
    manchmal auftritt und deshalb besonders teuer ist.
    """
    return json.dumps(
        {"ok": ok, "result": result, "error": error},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def sign_result(hmac_key: str, job_id: str, body: bytes) -> str:
    mac = hmac.new(hmac_key.encode("utf-8"), digestmod=hashlib.sha256)
    mac.update(job_id.encode("ascii"))
    mac.update(b"\x00")
    mac.update(body)
    return mac.hexdigest()


__all__ = ["canonical_result_body", "sign_result"]
