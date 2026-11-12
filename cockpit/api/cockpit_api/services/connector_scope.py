"""Was der Connector-Agent anfassen darf — Prüfung der OU-Freigabe (ADR-0014 Nachtrag).

Der Agent läuft auf dem Domänencontroller, mit dessen Rechten, und holt seine
OU-Freigabe aus dem Cockpit. Die Freigabe ist damit die Schranke zwischen der
Plattform und dem ganzen AD. Abgelehnt wird hier, und noch einmal im Agenten
selbst (``connector_agent.guardrails``), was nie eine Freigabe sein darf: die
ganze Domäne und die Container, in denen die Verwaltung des AD selbst liegt.
Dieselbe Liste auf beiden Seiten; ein Test hält sie gleich.
"""

from __future__ import annotations

import re

#: Container, die nie freigegeben werden — auch nicht als Teil eines längeren
#: DN darunter. Kleingeschrieben, ohne Leerzeichen nach Kommas.
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

MAX_OUS = 50
MAX_GROUPS = 100
_RDN = re.compile(r"^(ou|cn|dc)=[^,=]+$", re.IGNORECASE)


class ScopeError(ValueError):
    """Die Freigabe ist unzulässig. Die Meldung nennt den Eintrag."""


def normalize_dn(dn: str) -> str:
    """Kleinschreibung, keine Leerzeichen um die Kommas — für Vergleiche."""
    return ",".join(part.strip() for part in dn.strip().split(",")).lower()


def check_ou(dn: str) -> str:
    """Eine OU prüfen; gibt sie getrimmt zurück oder wirft :class:`ScopeError`."""
    text = ",".join(part.strip() for part in dn.strip().split(","))
    parts = [p for p in text.split(",") if p]
    if not parts or not all(_RDN.match(p) for p in parts):
        raise ScopeError(f"„{dn}“ ist kein Distinguished Name (OU=…,DC=…).")
    if parts[0].lower().startswith("dc="):
        raise ScopeError(f"„{dn}“ ist die ganze Domäne — das wäre jede OU.")
    if not any(p.lower().startswith("dc=") for p in parts):
        raise ScopeError(f"„{dn}“ hat keinen Domänenteil (DC=…).")
    lowered = [p.lower() for p in parts]
    for part in lowered:
        if part in FORBIDDEN_CONTAINERS:
            raise ScopeError(f"„{dn}“ liegt in {part} — das ist die Verwaltung des AD selbst.")
    return text


def check_scope(ous: list[str], groups: list[str]) -> tuple[list[str], list[str]]:
    if len(ous) > MAX_OUS:
        raise ScopeError(f"Höchstens {MAX_OUS} OUs.")
    if len(groups) > MAX_GROUPS:
        raise ScopeError(f"Höchstens {MAX_GROUPS} geschützte Gruppen.")
    unique: list[str] = []
    seen: set[str] = set()
    for ou in (check_ou(o) for o in ous if o.strip()):
        if normalize_dn(ou) not in seen:
            seen.add(normalize_dn(ou))
            unique.append(ou)
    cleaned_groups = sorted({g.strip().lower() for g in groups if g.strip()})
    if any(len(g) > 512 for g in cleaned_groups):
        raise ScopeError("Ein Gruppenname ist länger als 512 Zeichen.")
    return unique, cleaned_groups


__all__ = ["FORBIDDEN_CONTAINERS", "ScopeError", "check_ou", "check_scope", "normalize_dn"]
