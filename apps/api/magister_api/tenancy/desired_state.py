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
from typing import Any, cast

import httpx

from magister_api.tenancy.console_tls import ConsoleTlsError, console_verify

logger = logging.getLogger(__name__)


class DesiredStateUnavailableError(RuntimeError):
    """Der Soll-Zustand liess sich nicht holen. Kein Grund, etwas zu ändern."""


@dataclass(frozen=True)
class DesiredTemplate:
    """Eine globale Vorlage, wie die Konsole sie liefert (ADR-0018)."""

    key: str
    language: str
    subject: str | None
    body_html: str
    may_override: bool
    version: int


@dataclass(frozen=True)
class DesiredMaintenance:
    """Ein Wartungsauftrag aus der Konsole (ADR-0024 D4).

    Wird genau einmal ausgeführt: die Ausführung hinterlässt ein
    Audit-Ereignis mit der Auftrags-Id als Ziel, und ein Auftrag, zu dem es
    das schon gibt, wird nur noch gemeldet.
    """

    id: str
    action: str
    requested_by: str
    reason: str
    #: Auftragsparameter, nur Zeichenketten. Beim lokalen Admin-Konto:
    #: Benutzername, das **versiegelte** Passwort und ob der zweite Faktor
    #: zurückgesetzt wird. Nie Klartext — das versiegelte Passwort kann nur
    #: diese Datenebene öffnen.
    params: dict[str, str] = field(default_factory=dict[str, str])


#: Was die Konsole an Wartung auslösen darf. Eine Allowlist wie bei den
#: Einstellungen: ein unbekannter Auftrag wird nicht ausgeführt, sondern
#: als Fehler zurückgemeldet.
MAINTENANCE_ACTIONS: frozenset[str] = frozenset({"demo_purge", "audit_reset", "local_admin_setup"})


@dataclass(frozen=True)
class DesiredState:
    """Was für einen Kunden gelten soll."""

    settings: dict[str, Any] = field(default_factory=dict)
    #: {rollen_schlüssel: [capability, ...]}. Leer heisst **keine Vorgabe** —
    #: dann bleibt die Matrix des Kunden unangetastet. Der Unterschied zu
    #: „Vorgabe: keine Rechte" entscheidet, ob ein leeres Dokument eine ganze
    #: Installation entrechtet.
    rbac: dict[str, list[str]] = field(default_factory=dict)
    #: `None` heisst **keine Aussage** (eine Konsole, die das Feld nicht
    #: kennt); eine Liste ist **vollständig** und `[]` heisst „keine
    #: Plattformvorlagen" (ADR-0018 D6).
    #:
    #: Anders als bei `rbac`, wo eine leere Matrix „keine Vorgabe" heisst — und
    #: der Unterschied ist nicht Inkonsequenz, sondern der Zweck: eine Vorlage
    #: muss **zurückgezogen** werden können, eine Rechte-Matrix nicht. Wäre
    #: `[]` hier „keine Aussage", gäbe es keinen Weg, eine ausgelieferte
    #: Vorlage wieder zu entfernen.
    templates: tuple[DesiredTemplate, ...] | None = None
    settings_source: str = "platform"
    rbac_source: str = "platform"
    #: {name: chiffrat} — versiegelte Geheimnisse (ADR-0024 D3). Fehlt ein
    #: Name, wird nichts angefasst: entfernt wird ein Geheimnis nicht über
    #: den Abgleich.
    sealed_secrets: dict[str, str] = field(default_factory=dict)
    maintenance: tuple[DesiredMaintenance, ...] = ()

    @property
    def has_rbac(self) -> bool:
        return bool(self.rbac)

    @property
    def has_templates(self) -> bool:
        return self.templates is not None


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
        templates=_parse_templates(payload),
        settings_source=str(payload.get("settings_source") or "platform"),
        rbac_source=str(payload.get("rbac_source") or "platform"),
        sealed_secrets=_parse_sealed(payload),
        maintenance=_parse_maintenance(payload),
    )


def _parse_sealed(payload: dict[str, Any]) -> dict[str, str]:
    raw = payload.get("sealed_secrets")
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise DesiredStateUnavailableError("'sealed_secrets' ist kein Objekt.")
    out: dict[str, str] = {}
    for name, value in cast(dict[object, object], raw).items():
        if not isinstance(name, str) or not isinstance(value, str):
            raise DesiredStateUnavailableError("'sealed_secrets' hat die falsche Form.")
        out[name] = value
    return out


def _parse_maintenance(payload: dict[str, Any]) -> tuple[DesiredMaintenance, ...]:
    raw = payload.get("maintenance")
    if raw is None:
        return ()
    if not isinstance(raw, list):
        raise DesiredStateUnavailableError("'maintenance' ist keine Liste.")
    parsed: list[DesiredMaintenance] = []
    for index, entry in enumerate(cast(list[object], raw)):
        if not isinstance(entry, dict):
            raise DesiredStateUnavailableError(f"Wartungsauftrag {index} ist kein Objekt.")
        item = cast(dict[str, object], entry)
        try:
            parsed.append(
                DesiredMaintenance(
                    id=str(item["id"]),
                    action=str(item["action"]),
                    requested_by=str(item.get("requested_by") or ""),
                    reason=str(item.get("reason") or ""),
                    params=_parse_params(item.get("params"), index),
                )
            )
        except KeyError as exc:
            raise DesiredStateUnavailableError(
                f"Wartungsauftrag {index} hat nicht die erwartete Form: {exc}"
            ) from exc
    return tuple(parsed)


def _parse_params(raw: object, index: int) -> dict[str, str]:
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise DesiredStateUnavailableError(f"Wartungsauftrag {index}: 'params' ist kein Objekt.")
    out: dict[str, str] = {}
    for key, value in cast(dict[object, object], raw).items():
        if not isinstance(key, str) or not isinstance(value, str) or len(value) > 4096:
            raise DesiredStateUnavailableError(
                f"Wartungsauftrag {index}: 'params' hat die falsche Form."
            )
        out[key] = value
    return out


def _parse_templates(payload: dict[str, Any]) -> tuple[DesiredTemplate, ...] | None:
    """Die Vorlagen aus der Antwort — oder `None`, wenn keine drinstehen.

    `None` und `()` sind hier **nicht** dasselbe (ADR-0018 D6): fehlt der
    Schlüssel, hat die Konsole nichts über Vorlagen gesagt und es wird nichts
    angefasst; steht er als leere Liste da, ist die Aussage „keine" und der
    Abgleich räumt auf. Eine Konsole vor ADR-0018 liefert den Schlüssel nicht —
    und darf deshalb nicht als „alle Vorlagen entfernen" gelesen werden.
    """
    raw = payload.get("templates")
    if raw is None:
        return None
    if not isinstance(raw, list):
        raise DesiredStateUnavailableError("'templates' ist keine Liste.")
    parsed: list[DesiredTemplate] = []
    for index, entry in enumerate(raw):
        if not isinstance(entry, dict):
            raise DesiredStateUnavailableError(f"Vorlage {index} ist kein Objekt.")
        try:
            key = str(entry["key"])
            language = str(entry["language"])
            body_html = str(entry["body_html"])
            version = int(entry["version"])
        except (KeyError, TypeError, ValueError) as exc:
            raise DesiredStateUnavailableError(
                f"Vorlage {index} hat nicht die erwartete Form: {exc}"
            ) from exc
        if version < 1:
            # Die Fassungsnummer wird gegen eine quittierte verglichen. Eine 0
            # wäre von „noch nie quittiert" nicht zu unterscheiden.
            raise DesiredStateUnavailableError(f"Vorlage {key}/{language} hat Fassung {version}.")
        subject = entry.get("subject")
        parsed.append(
            DesiredTemplate(
                key=key,
                language=language,
                subject=None if subject is None else str(subject),
                body_html=body_html,
                may_override=bool(entry.get("may_override", True)),
                version=version,
            )
        )
    duplicates = len(parsed) - len({(t.key, t.language) for t in parsed})
    if duplicates:
        # Zwei Fassungen für dasselbe Paar: welche gilt, wäre Zufall der
        # Reihenfolge. Das ist keine Konfiguration, sondern ein Fehler.
        raise DesiredStateUnavailableError(
            f"{duplicates} doppelte Vorlage(n) im Soll-Zustand (gleicher Schlüssel und Sprache)."
        )
    return tuple(parsed)


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
        async with httpx.AsyncClient(timeout=timeout_s, verify=console_verify()) as client:
            response = await client.get(url, headers=headers)
    except (httpx.HTTPError, ConsoleTlsError) as exc:
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
    "DesiredTemplate",
    "DesiredStateUnavailableError",
    "fetch_desired_state",
    "parse_desired_state",
]
