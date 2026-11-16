"""Sperre für Rollen und Anmeldekonten, solange das Cockpit sie führt (ADR-0027).

Entscheid des Produktverantwortlichen (2026-11-16): Rollen und Benutzer nur
noch im Cockpit — „Die Kunden sollen dies nicht machen können, da es zu
gefährlich ist, dass wir neuen Benutzern bei einem Problem von aussen [Rechte]
geben können."

Die Sperre hängt an den **Endpunkten**, nicht an der Oberfläche: eine nur
lesbare Seite schützt nichts, wenn die API weiter annimmt. Sie gilt für jeden,
der sonst Rollen vergeben dürfte (Admin des Kunden, auch ein Bootstrap-Admin),
mit einer Ausnahme: das **lokale Administrationskonto** (Notzugang, ADR-0015
D2). Fällt der Abgleich aus oder ist im Cockpit etwas falsch eingetragen, muss
jemand beim Kunden noch handeln können; was er vergibt, meldet Magister dem
Cockpit als fremde Rolle (``rollen_fremd``).

Abgelehnt wird mit **409** und dem Kürzel :data:`ROLES_MANAGED_BY_COCKPIT`;
die Oberfläche übersetzt es („Rollen dieses Kunden vergibt der Betreiber im
Cockpit").
"""

from __future__ import annotations

from fastapi import Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from magister_api.auth.current_user import AuthenticatedUser
from magister_api.auth.rbac import require_admin
from magister_api.db import get_session
from magister_api.services.role_lock import roles_from_cockpit

#: ``detail`` der Ablehnung; zugleich der i18n-Schlüssel der Oberfläche.
ROLES_MANAGED_BY_COCKPIT = "roles_managed_by_cockpit"


def is_emergency_access(user: AuthenticatedUser) -> bool:
    """Das lokale Administrationskonto (Notzugang) — die einzige Ausnahme."""
    return user.auth_kind == "local"


async def roles_editable_here(session: AsyncSession, user: AuthenticatedUser) -> bool:
    """Darf ``user`` hier Rollen vergeben, entziehen und Anmeldekonten verwalten?"""
    return is_emergency_access(user) or not await roles_from_cockpit(session)


async def require_roles_editable(
    user: AuthenticatedUser = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
) -> AuthenticatedUser:
    """FastAPI-Abhängigkeit: 409, solange das Cockpit die Rollen führt.

    Hängt an ``require_admin`` (dieselbe Prüfung, von FastAPI je Anfrage nur
    einmal ausgeführt): ohne Anmeldung bleibt es bei 401, ohne Admin bei 403 —
    die Sperre verrät niemandem ohne Rechte, wer die Rollen führt.
    """
    if not await roles_editable_here(session, user):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=ROLES_MANAGED_BY_COCKPIT)
    return user


__all__ = [
    "ROLES_MANAGED_BY_COCKPIT",
    "is_emergency_access",
    "require_roles_editable",
    "roles_editable_here",
]
