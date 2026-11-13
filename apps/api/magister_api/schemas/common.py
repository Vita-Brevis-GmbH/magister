"""Shared validators for system-boundary types (UPN, login name, AD objectGUID).

Per CLAUDE.md "Immer"-Regel: validate UPN and objectGUID at the system boundary.
"""

from __future__ import annotations

import re
from typing import Annotated

from pydantic import AfterValidator

# UPN per RFC 5321/RFC 822 (simplified): user@domain, no whitespace, includes a dot in domain.
_UPN_RE = re.compile(r"^[A-Za-z0-9._%+\-]{1,64}@[A-Za-z0-9.\-]{1,253}\.[A-Za-z]{2,63}$")
# Lower-case canonical 8-4-4-4-12 hex form.
_GUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


def validate_upn(value: str) -> str:
    v = value.strip().lower()
    if not _UPN_RE.match(v):
        raise ValueError(f"invalid UPN: {value!r}")
    if len(v) > 320:
        raise ValueError("UPN exceeds 320 characters")
    return v


#: Längste Form eines Keycloak-Benutzernamens (ADR-0025).
LOGIN_NAME_MAX = 255


def validate_login_name(value: str) -> str:
    """Benutzername aus dem Keycloak-Realm (``preferred_username``, ADR-0025).

    Keycloak schreibt Benutzernamen klein und erlaubt mehr als ein UPN: auch
    ``automato-admin`` ohne ``@``. Die Regel hier ist bewusst die einfache, die
    beide Seiten (Magister und Cockpit) gleich prüfen können: klein, 1–255
    Zeichen, druckbar, ohne Leerraum.
    """
    v = value.strip().lower()
    if not v or len(v) > LOGIN_NAME_MAX:
        raise ValueError("invalid login name: length must be 1-255")
    if not v.isprintable() or any(ch.isspace() for ch in v):
        raise ValueError("invalid login name: must be printable without whitespace")
    return v


def validate_upn_or_login_name(value: str) -> str:
    """Ein UPN (AD, lokales Notkonto, Operator) oder ein Keycloak-Benutzername."""
    try:
        return validate_upn(value)
    except ValueError:
        return validate_login_name(value)


def validate_object_guid(value: str) -> str:
    v = value.strip().lower()
    # Strip braces if present, e.g. "{...}".
    if v.startswith("{") and v.endswith("}"):
        v = v[1:-1]
    if not _GUID_RE.match(v):
        raise ValueError(f"invalid AD objectGUID: {value!r}")
    return v


def validate_object_guid_or_empty(value: str) -> str:
    """Wie :func:`validate_object_guid`, lässt aber den leeren Wert zu.

    Für die **eine** Sitzungsart, die zu keinem AD-Objekt gehört: ein
    Operator-Zugriff (ADR-0019 D5). Ein erfundener Sentinel-GUID wäre bequemer
    und schlechter — er sähe in jeder Abfrage wie ein echter aus.
    """
    if value == "":
        return value
    return validate_object_guid(value)


Upn = Annotated[str, AfterValidator(validate_upn)]
LoginName = Annotated[str, AfterValidator(validate_login_name)]
UpnOrLoginName = Annotated[str, AfterValidator(validate_upn_or_login_name)]
ObjectGuid = Annotated[str, AfterValidator(validate_object_guid)]
ObjectGuidOrEmpty = Annotated[str, AfterValidator(validate_object_guid_or_empty)]
