"""Soll-Zustand von der Konsole abholen (ADR-0017 D3).

Dieselbe Bauart wie `console_registry`: die Datenebene **zieht**, die Konsole
schiebt nicht. Sie hat keinen Datenbankzugang zum Kunden, und das bleibt so.

Und dieselbe Zusage: ist die Konsole nicht erreichbar oder antwortet sie
unbrauchbar, bleibt der letzte gute Stand in Kraft. Ein leeres Ergebnis
ersetzt nichts — sonst setzte ein Fehler in der Konsole alle Kunden zurück.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

import httpx

logger = logging.getLogger(__name__)


class DesiredStateUnavailableError(RuntimeError):
    """Der Soll-Zustand liess sich nicht holen. Kein Grund, etwas zu ändern."""


@dataclass(frozen=True)
class DesiredState:
    """Was für einen Kunden gelten soll."""

    settings: dict[str, Any] = field(default_factory=dict)
    #: {rollen_schlüssel: [capability, ...]}. Leer heisst **keine Vorgabe** —
    #: dann bleibt die Matrix des Kunden unangetastet. Der Unterschied zu
    #: „Vorgabe: keine Rechte" entscheidet, ob ein leeres Dokument eine ganze
    #: Installation entrechtet.
    rbac: dict[str, list[str]] = field(default_factory=dict)
    settings_source: str = "platform"
    rbac_source: str = "platform"

    @property
    def has_rbac(self) -> bool:
        return bool(self.rbac)


def parse_desired_state(payload: object) -> DesiredState:
    """Antwort der Konsole prüfen und übernehmen.

    Streng, und zwar aus demselben Grund wie bei der Registry: was hier
    durchkommt, wird in das Schema eines Kunden geschrieben. Eine Antwort, die
    nicht die erwartete Form hat, ist keine Konfiguration, sondern ein Fehler
    — und ein Fehler darf nicht materialisiert werden.
    """
    if not isinstance(payload, dict):
        raise DesiredStateUnavailableError("Antwort der Konsole ist kein Objekt.")
    raw_settings = payload.get("settings")
    if not isinstance(raw_settings, dict):
        raise DesiredStateUnavailableError("'settings' fehlt oder ist kein Objekt.")
    raw_rbac = payload.get("rbac", {})
    if not isinstance(raw_rbac, dict):
        raise DesiredStateUnavailableError("'rbac' ist kein Objekt.")
    rbac: dict[str, list[str]] = {}
    for role, caps in raw_rbac.items():
        if not isinstance(role, str) or not isinstance(caps, list):
            raise DesiredStateUnavailableError(f"Rechte-Eintrag {role!r} hat die falsche Form.")
        if not all(isinstance(c, str) for c in caps):
            raise DesiredStateUnavailableError(f"Rechte von {role!r} sind keine Namensliste.")
        rbac[role] = list(caps)
    return DesiredState(
        settings=dict(raw_settings),
        rbac=rbac,
        settings_source=str(payload.get("settings_source") or "platform"),
        rbac_source=str(payload.get("rbac_source") or "platform"),
    )


async def fetch_desired_state(
    console_url: str,
    tenant_console_id: str,
    *,
    token: str,
    timeout_s: float = 5.0,
    management_marker: str = "",
) -> DesiredState:
    """Den Soll-Zustand eines Kunden holen.

    ``console_url`` ist die Registry-Adresse; der Pfad wird daraus abgeleitet,
    damit es nicht eine zweite Einstellung gibt, die mit der ersten
    auseinanderlaufen kann.
    """
    base = console_url.rstrip("/")
    if base.endswith("/tenants/registry"):
        base = base[: -len("/tenants/registry")]
    url = f"{base}/tenants/{tenant_console_id}/desired-state"
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    if management_marker:
        headers["X-Magister-Management"] = management_marker
    try:
        async with httpx.AsyncClient(timeout=timeout_s) as client:
            response = await client.get(url, headers=headers)
    except httpx.HTTPError as exc:
        raise DesiredStateUnavailableError(f"Konsole nicht erreichbar: {exc}") from exc
    if response.status_code != 200:
        # Kein Token im Text: die Meldung geht in den Log.
        raise DesiredStateUnavailableError(
            f"Konsole antwortete mit HTTP {response.status_code} auf den Soll-Zustand."
        )
    try:
        payload = response.json()
    except ValueError as exc:
        raise DesiredStateUnavailableError(f"Antwort der Konsole ist kein JSON: {exc}") from exc
    return parse_desired_state(payload)


__all__ = [
    "DesiredState",
    "DesiredStateUnavailableError",
    "fetch_desired_state",
    "parse_desired_state",
]
