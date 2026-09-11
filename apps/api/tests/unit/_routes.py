"""Die Routen einer Anwendung aufzählen — über FastAPI-Versionen hinweg.

Zwei Contract-Tests hängen daran (`test_platform_managed_surface`,
`test_operator_read_only_surface`), und beide behaupten etwas über **alle**
Routen. Eine Aufzählung, die nichts findet, macht aus so einem Test einen, der
immer grün ist.

Genau das stand kurz bevor: FastAPI legt eingebundene Router nicht in jeder
Fassung flach in `app.routes` ab. Bis 0.136 waren es `APIRoute`-Objekte mit
vollem Pfad; ab 0.141 (in der Konsole schon im Einsatz) steht dort ein
`_IncludedRouter`, und `getattr(route, "path", None)` ist `None`. Die Tests
hätten nach einem Upgrade der Datenebene **nichts mehr geprüft** und wären
grün geblieben.

Deshalb dieser Helfer: er steigt in eingebundene Router hinein und setzt die
Präfixe zusammen. Und deshalb :func:`api_routes` mit einer Untergrenze — eine
Anwendung dieser Grösse hat dutzende Routen; findet die Aufzählung fast keine,
ist die Aufzählung kaputt und nicht die Anwendung.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

from fastapi import FastAPI

#: Untergrenze für die Plausibilität. Bewusst niedrig: der Test soll auf eine
#: **kaputte Aufzählung** anschlagen, nicht auf jede entfernte Route.
MIN_EXPECTED_ROUTES = 40


@dataclass(frozen=True)
class RouteInfo:
    path: str
    methods: frozenset[str]
    dependant: Any


def _walk(routes: list[Any], prefix: str) -> Iterator[RouteInfo]:
    for route in routes:
        path = getattr(route, "path", None)
        if path is not None and getattr(route, "methods", None) is not None:
            yield RouteInfo(
                path=f"{prefix}{path}",
                methods=frozenset(route.methods or ()),
                dependant=getattr(route, "dependant", None),
            )
            continue
        # Ab FastAPI 0.141: ein `_IncludedRouter`. Der eingebundene Router steht
        # in `original_router`, das Präfix der Einbindung in
        # `include_context.prefix`. Das Präfix des Routers selbst steckt
        # **schon** in den Pfaden seiner Routen (`/instances`), es darf also
        # nicht noch einmal davor — sonst käme `/api/instances/instances`
        # heraus. Nachgesehen, nicht angenommen.
        included = getattr(route, "original_router", None)
        if included is not None:
            context = getattr(route, "include_context", None)
            mount_prefix = getattr(context, "prefix", "") or ""
            yield from _walk(list(included.routes), f"{prefix}{mount_prefix}")
            continue
        # Ein Mount (z. B. eine untergehängte Anwendung).
        child = getattr(route, "app", None)
        child_routes = getattr(child, "routes", None) if child is not None else None
        if not child_routes:
            continue
        yield from _walk(list(child_routes), f"{prefix}{path or ''}")


def api_routes(app: FastAPI, *, require_many: bool = True) -> list[RouteInfo]:
    """Alle Routen mit Pfad und Methoden, rekursiv.

    `require_many=False` nur für Tests, die absichtlich eine winzige
    Anwendung bauen.
    """
    found = list(_walk(list(app.routes), ""))
    if require_many:
        assert len(found) >= MIN_EXPECTED_ROUTES, (
            f"Die Routen-Aufzählung fand nur {len(found)} Routen. Das ist keine "
            "Anwendung dieser Grösse — vermutlich legt FastAPI eingebundene "
            "Router in einer neuen Fassung anders ab. `tests/unit/_routes.py` "
            "muss mit, sonst prüfen die Contract-Tests nichts mehr."
        )
    return found


def paths(app: FastAPI) -> set[str]:
    return {route.path for route in api_routes(app)}


__all__ = ["MIN_EXPECTED_ROUTES", "RouteInfo", "api_routes", "paths"]
