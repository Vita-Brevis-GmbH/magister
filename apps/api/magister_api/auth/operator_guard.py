"""Ein Operator-Zugriff darf lesen — eine Prüfung, für alle Routen (ADR-0019 D1).

Der Entwurf davor war eine **Ausschlussliste**: Operator darf alles ausser
Passwörter lesen, ausser Benutzer anlegen, ausser … Beim Aufschreiben kam
heraus, wie lang sie ist — sechs Dienste geben ein Klartext-Passwort heraus
(Passwortliste einer Klasse, Zugangsdaten-PDF, drei Reset-Wege,
Benutzeranlage), und jeder neue Endpunkt müsste daran denken. Eine Liste, die
jemand ergänzen muss, ist eine Liste, die eines Tages nicht ergänzt wird.

Mit der Methodenregel fallen fünf der sechs von selbst weg: sie sind `POST`.
Übrig bleibt genau **eine** Leseroute, die ein Klartext-Passwort zeigt, und die
steht unten.

Die Prüfung sitzt in ``get_optional_user`` und damit an jedem Endpunkt, der
überhaupt eine Sitzung ansieht. Ein Endpunkt ohne Sitzung ist unauthentisiert,
und dort ist eine Operator-Sitzung ohne Belang.
"""

from __future__ import annotations

import re

from fastapi import HTTPException, Request, status

#: Methoden, die nichts ändern.
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})

#: Die **eine** Ausnahme in die andere Richtung: den eigenen Zugriff beenden.
#: Sie erweitert nichts — sie erlaubt, früher aufzuhören, und setzt beim Kunden
#: sichtbar ``ended_at``. Ohne sie müsste ein Operator warten, bis die Stunde
#: um ist.
OPERATOR_ALLOWED_PATHS = frozenset({"/auth/logout"})

#: Leseroute, die trotzdem gesperrt ist: das PDF mit den gespeicherten
#: Passwörtern einer Klasse. Der Kunde darf das drucken, der Betreiber nicht.
#:
#: Auf den konkreten Pfad geprüft und nicht auf die Routen-Vorlage: welche
#: Attribute Starlette in ``scope`` ablegt, ist eine Eigenschaft der Version.
#: Ein Muster auf dem Pfad hängt an nichts.
OPERATOR_DENIED_READS: tuple[re.Pattern[str], ...] = (
    re.compile(r"^/classes/\d+/password-list/?$"),
)


class OperatorReadOnlyError(HTTPException):
    def __init__(self, detail: str) -> None:
        super().__init__(status_code=status.HTTP_403_FORBIDDEN, detail=detail)


def deny_unsafe_for_operator(request: Request) -> None:
    """Wirft 403, wenn eine Operator-Sitzung etwas anderes als lesen will."""
    path = request.url.path
    if request.method not in SAFE_METHODS:
        if path.rstrip("/") in OPERATOR_ALLOWED_PATHS:
            return
        raise OperatorReadOnlyError("operator_read_only")
    if any(pattern.match(path) for pattern in OPERATOR_DENIED_READS):
        raise OperatorReadOnlyError("operator_no_passwords")


__all__ = [
    "OPERATOR_ALLOWED_PATHS",
    "OPERATOR_DENIED_READS",
    "SAFE_METHODS",
    "OperatorReadOnlyError",
    "deny_unsafe_for_operator",
]
