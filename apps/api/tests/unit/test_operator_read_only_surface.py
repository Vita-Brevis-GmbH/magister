"""Jede schreibende Route läuft durch die Operator-Prüfung (ADR-0019 D1).

Der Entscheid lautet „eine Prüfung, an einer Stelle, für alle Routen — auch
für die, die es nächstes Jahr gibt". Das ist eine Behauptung über die
**ganze** Anwendung, und sie lässt sich nur so prüfen: die Routen durchgehen
und nachsehen, ob jede schreibende eine Sitzungsabhängigkeit hat.

Denn dort sitzt die Prüfung: `deny_unsafe_for_operator` läuft in
`get_optional_user`. Eine schreibende Route ohne Sitzungsabhängigkeit ist
unauthentisiert — und wäre damit nicht erfasst. Dass es davon genau fünf gibt
und welche, steht unten; jede weitere muss hier eingetragen und begründet
werden.

Ein Testentwurf davor prüfte `POST` auf erfundene Pfade und bekam 404 und 405:
die Prüfung ist eine **Abhängigkeit** und läuft erst, wenn eine Route gefunden
wurde. Dieser Test ist die Antwort darauf.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519
from fastapi import FastAPI

from magister_api.auth.current_user import get_current_user, get_optional_user
from magister_api.auth.operator_guard import OPERATOR_ALLOWED_PATHS, SAFE_METHODS
from magister_api.config import Settings
from magister_api.main import create_app
from tests.unit._routes import api_routes

#: Schreibende Routen **ohne** Sitzung — und warum das jeweils in Ordnung ist.
#: Wer hier etwas einträgt, schreibt den Grund dazu.
UNAUTHENTICATED_WRITES: dict[str, str] = {
    "/auth/login/local": (
        "Anmeldung des Notfallkontos. Sie geht der Sitzung voraus; eine "
        "Sitzungsabhängigkeit wäre hier ein Zirkel."
    ),
    "/auth/login/local/enroll": "Zweiter Faktor einrichten — noch vor der Sitzung.",
    "/auth/login/local/totp": "Zweiter Schritt derselben Anmeldung.",
    "/internal/ad-rpc/{method}": (
        "Interne RPC-Fläche zwischen den Containern (ADR-0011). Sie wird von "
        "Caddy nie von aussen geroutet und trägt ihr eigenes Geheimnis; eine "
        "Browser-Sitzung gibt es dort nicht."
    ),
    "/operator/redeem": (
        "Das Einlösen selbst (ADR-0019). Der Einlöseschein ist das "
        "Zugangsmittel — es gibt zu diesem Zeitpunkt keine Sitzung."
    ),
}


@pytest.fixture(scope="module")
def app() -> FastAPI:
    key = ed25519.Ed25519PrivateKey.generate()
    pem = (
        key.public_key()
        .public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode("ascii")
    )
    return create_app(
        Settings(
            audit_key="k" * 32,  # type: ignore[arg-type]
            session_secret="s" * 32,  # type: ignore[arg-type]
            csrf_secret="c" * 32,  # type: ignore[arg-type]
            operator_public_key=pem,
        )
    )


def _calls(dependant: Any) -> Iterator[Any]:
    yield dependant.call
    for sub in dependant.dependencies:
        yield from _calls(sub)


def _write_routes(app: FastAPI) -> list[tuple[str, frozenset[str], Any]]:
    """Jede Route mit einer schreibenden Methode.

    Über `api_routes` und nicht über `app.routes`: seit FastAPI 0.141 liegen
    eingebundene Router dort als `_IncludedRouter` ohne `path`, und dieser Test
    hätte nach einem Upgrade **nichts** mehr gefunden — und wäre grün
    geblieben. Der Helfer steigt hinein und hat eine Untergrenze.
    """
    out: list[tuple[str, frozenset[str], Any]] = []
    for route in api_routes(app):
        methods = route.methods - SAFE_METHODS
        if methods:
            out.append((route.path, methods, route.dependant))
    return out


class TestEveryWriteRouteIsCovered:
    def test_the_enumeration_finds_something(self, app: FastAPI) -> None:
        """Die Prüfung, die diesen Test vor sich selbst schützt.

        Ein Contract-Test über „alle Routen" ist wertlos, wenn die Aufzählung
        leer ist. Zwanzig schreibende Routen sind für diese Anwendung
        konservativ tief.
        """
        assert len(_write_routes(app)) >= 20

    def test_no_uncovered_write_route(self, app: FastAPI) -> None:
        uncovered: list[str] = []
        for path, methods, dependant in _write_routes(app):
            if path in UNAUTHENTICATED_WRITES:
                continue
            if dependant is None:
                uncovered.append(f"{sorted(methods)} {path} (kein dependant)")
                continue
            calls = set(_calls(dependant))
            if get_optional_user not in calls and get_current_user not in calls:
                uncovered.append(f"{sorted(methods)} {path}")
        assert uncovered == [], (
            "Diese schreibenden Routen hängen an keiner Sitzung und laufen "
            f"damit nicht durch die Operator-Prüfung: {uncovered}. Entweder sie "
            "bekommen eine Sitzungsabhängigkeit, oder sie werden in "
            "UNAUTHENTICATED_WRITES mit Begründung eingetragen (ADR-0019 D1)."
        )

    def test_the_allowlist_has_no_stale_entries(self, app: FastAPI) -> None:
        """Eine Ausnahme, deren Route es nicht mehr gibt, ist eine Falle.

        Sie steht dann für eine Route, die jemand später unter demselben Pfad
        neu anlegt — und wäre stillschweigend ausgenommen.
        """
        paths = {path for path, _methods, _dep in _write_routes(app)}
        stale = sorted(set(UNAUTHENTICATED_WRITES) - paths)
        assert stale == [], f"Ausnahmen ohne Route: {stale}"

    def test_every_exception_carries_a_reason(self) -> None:
        for path, reason in UNAUTHENTICATED_WRITES.items():
            assert len(reason) > 30, f"Die Begründung für {path} ist keine."


class TestTheOneAllowedMutation:
    def test_only_logout(self) -> None:
        """Die Ausnahme in die andere Richtung ist genau eine.

        Sie erweitert nichts: sie erlaubt einem Operator, früher aufzuhören.
        Käme hier etwas dazu, wäre das ein Schreibrecht — und dann stimmt der
        Satz „die Frage 'was hat der Operator geändert?' hat immer die Antwort
        'nichts'" nicht mehr.
        """
        assert OPERATOR_ALLOWED_PATHS == frozenset({"/auth/logout"})
