"""Grenzen, die der Agent selbst zieht (ADR-0014, Nachtrag „Agent auf dem DC").

Der Kern dieses Moduls ist eine unbequeme Annahme: **die Plattform könnte
kompromittiert sein.** Der Agent läuft auf dem Domänencontroller und bindet
sich als dessen Maschinenkonto ans AD. Wer die Plattform übernimmt, könnte ihm
sonst befehlen, ein Konto nach ``OU=Domain Controllers`` zu verschieben oder in
``Domain Admins`` aufzunehmen.

Seit dem Nachtrag kommt die **OU-Freigabe aus dem Cockpit** — der Betreiber
pflegt sie dort, nicht in einer Datei auf dem DC. Was der Agent trotzdem
**lokal** und unabänderlich festhält, und was die Plattform weder ändern noch
abschalten kann:

1. **Methoden-Allowlist** — dieselbe Menge wie plattformseitig. Doppelt, weil
   die zweite Prüfung diejenige ist, die auch dann noch gilt, wenn die erste
   umgangen wurde.
2. **Verbotene Container** — die ganze Domäne, ``Domain Controllers``,
   ``Builtin``, ``System``, ``Configuration`` … sind nie eine Freigabe und nie
   ein Ziel, egal was das Cockpit schickt (:data:`FORBIDDEN_CONTAINERS`,
   wörtlich wie im Cockpit; ein Test hält beide gleich).
3. **OU-Freigabe** — jeder DN in einem Auftrag muss unterhalb einer
   freigegebenen OU liegen. Leer heisst: keine Verzeichnisaufträge.
4. **Geschützte Gruppen** — die eingebaute Liste ist eine Untergrenze; das
   Cockpit kann Gruppen hinzufügen, keine entfernen.
5. **Geschützte Konten** — ein Konto mit ``adminCount=1`` (AdminSDHolder)
   oder ``isCriticalSystemObject`` fasst der Agent nicht an. Das prüft
   :class:`connector_agent.runner.AdExecutor` vor jeder Änderung im AD selbst,
   weil es eine Eigenschaft des Kontos ist und nicht des Auftrags.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, cast

logger = logging.getLogger(__name__)

#: Wörtlich die Allowlist der Plattform (``magister_api/ad/rpc.py``). Hier
#: wiederholt, weil der Agent eigenständig lauffähig sein muss; ein Test hält
#: die Mengen zusammen.
ALLOWED_METHODS: frozenset[str] = frozenset(
    {
        "find_user_dn",
        "fetch_user_groups",
        "probe_service_connection",
        "probe_service_connection_detailed",
        "probe_bind_as_user",
        "modify_password",
        "modify_user_attributes",
        "rename_user",
        "set_proxy_addresses",
        "set_account_enabled",
        "set_password_never_expires",
        "set_cannot_change_password",
        "delete_user_object",
        "add_user_to_groups",
        "remove_user_from_groups",
        "create_user",
        # Der Abgleich über den Agenten (ADR-0022 D1). Die einzige Methode,
        # die viel zurückgibt — die Grenzen unten gelten für sie genauso:
        # `search_base` ist ein DN und muss in einer erlaubten OU liegen.
        "search_users",
    }
)

#: Container, die nie freigegeben werden und nie Ziel eines Auftrags sind —
#: auch nicht als Teil eines längeren DN darunter. Kleingeschrieben, ohne
#: Leerzeichen. Wörtlich wie ``cockpit_api/services/connector_scope.py``.
FORBIDDEN_CONTAINERS: frozenset[str] = frozenset(
    {
        "ou=domain controllers",
        "cn=builtin",
        "cn=system",
        "cn=configuration",
        "cn=schema",
        "cn=program data",
        "cn=microsoft exchange system objects",
        "cn=managed service accounts",
        "cn=foreignsecurityprincipals",
    }
)

#: Methoden, die ein bestehendes Konto verändern. Vor ihnen prüft der Agent im
#: AD, ob das Ziel ein geschütztes Konto ist (``adminCount``).
MUTATING_USER_METHODS: frozenset[str] = frozenset(
    {
        "modify_password",
        "modify_user_attributes",
        "rename_user",
        "set_proxy_addresses",
        "set_account_enabled",
        "set_password_never_expires",
        "set_cannot_change_password",
        "delete_user_object",
        "add_user_to_groups",
        "remove_user_from_groups",
    }
)

#: Gruppen, in die nie geschrieben wird. Auf ``cn=`` verglichen, klein
#: geschrieben. Bewusst beide Sprachen: ein deutschsprachiges AD hat
#: ``Domänen-Admins``, und eine Denylist, die nur englisch kann, ist bei einem
#: Schweizer Kunden wertlos.
DEFAULT_PROTECTED_GROUPS: frozenset[str] = frozenset(
    {
        "domain admins",
        "domänen-admins",
        "domaenen-admins",
        "enterprise admins",
        "organisations-admins",
        "schema admins",
        "schema-admins",
        "administrators",
        "administratoren",
        "account operators",
        "konten-operatoren",
        "backup operators",
        "sicherungs-operatoren",
        "server operators",
        "server-operatoren",
        "print operators",
        "druck-operatoren",
        "group policy creator owners",
        "richtlinien-ersteller-besitzer",
        "dnsadmins",
        "protected users",
        "geschützte benutzer",
        "key admins",
        "schlüssel-admins",
        "cert publishers",
        "zertifikatherausgeber",
        "remote desktop users",
    }
)

#: Attribute, die der Agent nicht setzt — auch nicht, wenn ein Auftrag es
#: verlangt. ``memberof`` ist berechnet, die anderen sind Wege, ein Konto zu
#: privilegieren oder die Identität zu übernehmen.
PROTECTED_ATTRIBUTES: frozenset[str] = frozenset(
    {
        "memberof",
        "primarygroupid",
        "admincount",
        "useraccountcontrol",
        "serviceprincipalname",
        "msds-allowedtodelegateto",
        "msds-keycredentiallink",
        "sidhistory",
        "objectsid",
        "ntsecuritydescriptor",
    }
)

#: Schlüssel in einer Nutzlast, die einen DN tragen. Alles hier wird gegen die
#: OU-Allowlist geprüft.
_DN_KEYS: frozenset[str] = frozenset({"user_dn", "ou_dn", "search_base"})

#: Schlüssel, die eine Liste von Gruppen-DNs tragen.
_GROUP_LIST_KEYS: frozenset[str] = frozenset({"group_dns"})


class GuardrailViolationError(RuntimeError):
    """Der Auftrag verletzt eine lokale Grenze und wird nicht ausgeführt.

    Der Text geht an die Plattform zurück (als Fehlergrund) und in das lokale
    Protokoll. Er nennt die Regel, nicht den Inhalt: der Kunde soll sehen,
    *dass* etwas abgelehnt wurde und warum, ohne dass Personendaten in ein
    Plattform-Log wandern.
    """


def normalize_dn(dn: str) -> str:
    """DN für den Vergleich vereinheitlichen.

    LDAP-DNs sind gross-/kleinschreibungsunabhängig und dürfen Leerzeichen um
    die Kommas haben. ``CN=A, OU=X,DC=y`` und ``cn=a,ou=x,dc=y`` sind derselbe
    DN — ein naiver ``endswith``-Vergleich würde das übersehen und damit eine
    Allowlist umgehbar machen.
    """
    parts = [p.strip() for p in re.split(r"(?<!\\),", dn.strip()) if p.strip()]
    return ",".join(parts).lower()


def forbidden_part(dn: str) -> str | None:
    """Der verbotene Container in ``dn`` — oder ``None``."""
    for part in normalize_dn(dn).split(","):
        if part in FORBIDDEN_CONTAINERS:
            return part
    return None


def refusal_for_base(dn: str) -> str | None:
    """Warum ``dn`` keine OU-Freigabe sein darf — oder ``None``, wenn er es darf.

    Dieselben Regeln wie ``connector_scope.check_ou`` im Cockpit. Das Cockpit
    lehnt solche Einträge schon beim Speichern ab; hier steht die Prüfung ein
    zweites Mal, für den Fall, dass nicht das Cockpit sie geschickt hat.
    """
    parts = normalize_dn(dn).split(",") if dn.strip() else []
    if not parts or not all(re.match(r"^(ou|cn|dc)=[^=]+$", p) for p in parts):
        return "kein Distinguished Name"
    if parts[0].startswith("dc="):
        return "die ganze Domäne"
    if not any(p.startswith("dc=") for p in parts):
        return "ohne Domänenteil"
    hit = forbidden_part(dn)
    if hit is not None:
        return f"liegt in {hit}"
    return None


def dn_is_within(dn: str, allowed_bases: frozenset[str]) -> bool:
    """Liegt ``dn`` unterhalb einer erlaubten Basis (oder ist sie selbst)?

    Der Vergleich läuft über **RDN-Grenzen**, nicht über Zeichenketten:
    ``ou=schuleab,dc=x`` darf nicht als „innerhalb von ``ou=schule,dc=x``"
    gelten, nur weil der Text passt.
    """
    if not allowed_bases:
        return False
    target = normalize_dn(dn)
    for base in allowed_bases:
        normalized = normalize_dn(base)
        if target == normalized or target.endswith("," + normalized):
            return True
    return False


@dataclass(frozen=True, slots=True)
class Guardrails:
    """Die lokal konfigurierten Grenzen."""

    allowed_ous: frozenset[str] = field(default_factory=frozenset[str])
    protected_groups: frozenset[str] = field(default_factory=lambda: DEFAULT_PROTECTED_GROUPS)
    protected_attributes: frozenset[str] = field(default_factory=lambda: PROTECTED_ATTRIBUTES)

    def check(self, method: str, payload: dict[str, Any]) -> None:
        """Auftrag prüfen. Kehrt still zurück oder wirft."""
        self._check_method(method)
        self._check_dns(method, payload)
        self._check_groups(method, payload)
        self._check_attributes(method, payload)

    # -- einzelne Grenzen -------------------------------------------------
    def _check_method(self, method: str) -> None:
        if method not in ALLOWED_METHODS:
            raise GuardrailViolationError(
                f"Methode {method!r} steht nicht in der Allowlist des Agenten."
            )

    def _check_dns(self, method: str, payload: dict[str, Any]) -> None:
        if not self.allowed_ous:
            # Leere Allowlist heisst NICHT "alles erlaubt". Eine Grenze, die
            # sich durch Weglassen der Konfiguration abschalten lässt, ist
            # keine Grenze — und ein leeres Feld ist der wahrscheinlichste
            # Konfigurationsfehler.
            for key in _DN_KEYS | _GROUP_LIST_KEYS:
                if payload.get(key):
                    raise GuardrailViolationError(
                        "Es ist keine OU-Allowlist konfiguriert. Der Agent führt "
                        "keine Aufträge auf Verzeichnisobjekte aus, solange nicht "
                        "steht, wo er arbeiten darf."
                    )
            return
        for key in _DN_KEYS:
            dn: object = payload.get(key)
            if isinstance(dn, str) and dn and forbidden_part(dn) is not None:
                raise GuardrailViolationError(
                    f"{key} liegt in einem gesperrten AD-Container ({method})."
                )
            if isinstance(dn, str) and dn and not dn_is_within(dn, self.allowed_ous):
                raise GuardrailViolationError(
                    f"{key} liegt ausserhalb der erlaubten OUs ({method})."
                )
        for key in _GROUP_LIST_KEYS:
            for dn in _as_list(payload.get(key)):
                if isinstance(dn, str) and dn and forbidden_part(dn) is not None:
                    raise GuardrailViolationError(
                        f"Gruppen-DN in {key} liegt in einem gesperrten AD-Container ({method})."
                    )
                if isinstance(dn, str) and dn and not dn_is_within(dn, self.allowed_ous):
                    raise GuardrailViolationError(
                        f"Gruppen-DN in {key} liegt ausserhalb der erlaubten OUs ({method})."
                    )

    def _check_groups(self, method: str, payload: dict[str, Any]) -> None:
        for key in _GROUP_LIST_KEYS:
            for dn in _as_list(payload.get(key)):
                if not isinstance(dn, str):
                    continue
                cn = _leading_cn(dn)
                if cn is not None and cn in self.protected_groups:
                    raise GuardrailViolationError(
                        f"Gruppe {cn!r} steht auf der Denylist des Agenten ({method}). "
                        "Privilegierte Gruppen werden nicht über die Plattform verändert."
                    )

    def _check_attributes(self, method: str, payload: dict[str, Any]) -> None:
        attributes: object = payload.get("attributes")
        if not isinstance(attributes, dict):
            return
        for name in cast(dict[Any, Any], attributes):
            if str(name).strip().lower() in self.protected_attributes:
                raise GuardrailViolationError(
                    f"Attribut {name!r} wird vom Agenten nicht gesetzt: es ist ein Weg, "
                    "ein Konto zu privilegieren oder eine Identität zu übernehmen."
                )


def _as_list(value: object) -> list[Any]:
    """Liste aus einer Nutzlast holen, ohne über ihren Typ zu raten."""
    if isinstance(value, list):
        return cast(list[Any], value)
    return []


def _leading_cn(dn: str) -> str | None:
    first = normalize_dn(dn).split(",", 1)[0]
    if not first.startswith("cn="):
        return None
    return first[3:].strip()


__all__ = [
    "ALLOWED_METHODS",
    "DEFAULT_PROTECTED_GROUPS",
    "FORBIDDEN_CONTAINERS",
    "MUTATING_USER_METHODS",
    "PROTECTED_ATTRIBUTES",
    "GuardrailViolationError",
    "Guardrails",
    "dn_is_within",
    "forbidden_part",
    "normalize_dn",
    "refusal_for_base",
]
