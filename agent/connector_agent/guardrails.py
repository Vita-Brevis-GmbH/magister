"""Grenzen, die der Agent selbst zieht (ADR-0014).

Der Kern dieses Moduls ist eine unbequeme Annahme: **die Plattform könnte
kompromittiert sein.** Der Agent läuft im Kundennetz mit einem Dienstkonto, das
Passwörter setzen und Gruppen ändern darf. Wer die Plattform übernimmt, könnte
ihm sonst befehlen, einen Benutzer nach ``OU=Domain Controllers`` zu verschieben
oder in ``Domain Admins`` aufzunehmen.

Deshalb prüft der Agent **jeden** Auftrag noch einmal gegen Grenzen, die
**lokal** konfiguriert sind — in seiner eigenen Konfigurationsdatei beim Kunden,
nicht von der Plattform geliefert. Die Plattform kann sie nicht ändern, nicht
lesen und nicht abschalten.

Drei Grenzen:

1. **Methoden-Allowlist** — dieselbe Menge wie plattformseitig. Doppelt, weil
   die zweite Prüfung diejenige ist, die auch dann noch gilt, wenn die erste
   umgangen wurde.
2. **OU-Allowlist** — jeder DN in einem Auftrag muss unterhalb einer erlaubten
   OU liegen. Betrifft Ziel und Quelle: ein ``rename_user`` mit einem DN
   ausserhalb wird abgelehnt.
3. **Gruppen-Denylist** — Gruppen, in die der Agent niemandem hineinschreibt,
   auch nicht auf Befehl. Vorgabe deckt die üblichen privilegierten Gruppen ab,
   und zwar sprachunabhängig über die well-known RID-Namen *und* die deutschen
   Bezeichnungen, weil ein deutschsprachiges AD ``Domänen-Admins`` heisst.
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
_DN_KEYS: frozenset[str] = frozenset({"user_dn", "ou_dn"})

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
            if isinstance(dn, str) and dn and not dn_is_within(dn, self.allowed_ous):
                raise GuardrailViolationError(
                    f"{key} liegt ausserhalb der erlaubten OUs ({method})."
                )
        for key in _GROUP_LIST_KEYS:
            for dn in _as_list(payload.get(key)):
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
    "PROTECTED_ATTRIBUTES",
    "GuardrailViolationError",
    "Guardrails",
    "dn_is_within",
    "normalize_dn",
]
