"""Fremde Rollen melden und auf Wunsch des Cockpits entziehen (ADR-0027).

Führt das Cockpit die Rollen eines Kunden, vergibt Magister von Hand keine mehr
(``auth.role_lock``). Was vorher von Hand oder per Bootstrap vergeben wurde,
bleibt aber stehen — der Abgleich fasst nur Zuweisungen mit Herkunft
``cockpit`` an (ADR-0026 D3). Damit diese Altlasten sichtbar werden und weg
können:

* :func:`foreign_roles` liefert sie für die Zustandsmeldung (``rollen_fremd``):
  je Person und Rolle **ein** Eintrag — das Cockpit kennt keine Einheiten, eine
  Rolle gilt dort für den ganzen Kunden —, höchstens
  :data:`FOREIGN_ROLES_MAX`, ohne weitere Personendaten.
* :class:`ForeignRoleRevoker` entzieht, was das Cockpit im Soll-Zustand unter
  ``role_revocations`` nennt — aber **nur**, was hier als fremd gilt, an allen
  Einheiten der Person, jede Zeile auditiert.

Nicht fremd, also weder gemeldet noch entziehbar:

* Zuweisungen aus dem Cockpit (``granted_by = "cockpit"``);
* das lokale Administrationskonto (Notzugang, :data:`LOCAL_ADMIN_GUID`);
* die Admin-Rolle eines ersten Administrators aus der Konsole
  (``bootstrap_admins``) — sie kommt bei seiner nächsten Anmeldung ohnehin
  wieder und steht schon im Cockpit (Einstellungen des Kunden).
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from magister_api.audit.service import AuditService
from magister_api.auth.bootstrap import is_bootstrap_admin
from magister_api.auth.effective_settings import load_effective_settings
from magister_api.auth.roles import GRANTED_BY_COCKPIT, ROLE_ADMIN
from magister_api.config import Settings
from magister_api.models.auth import AdUserCache, RoleAssignment
from magister_api.repositories.auth import LoginAccountRepository, RoleAssignmentRepository
from magister_api.schemas.common import validate_login_name
from magister_api.services.local_admin import LOCAL_ADMIN_GUID
from magister_api.tenancy.desired_state import DesiredRoleRevocation

logger = logging.getLogger(__name__)

#: Höchstens so viele Einträge trägt ``rollen_fremd`` (Vertrag mit dem Cockpit).
FOREIGN_ROLES_MAX = 200

#: ``via`` im Audit eines Entzugs auf Wunsch des Cockpits.
VIA_COCKPIT_REVOCATION = "cockpit_revocation"

#: Ohne Herkunft (Zeilen von Hand per SQL, Runbook vor ADR-0026).
_UNKNOWN_SOURCE = "unbekannt"


@dataclass(frozen=True)
class ForeignRole:
    """Eine fremde Rolle einer Person, über alle ihre Einheiten."""

    principal: str
    role: str
    #: Keycloak-Benutzername des Anmeldekontos, sonst der UPN aus dem AD,
    #: sonst `None`.
    username: str | None
    #: Herkunft der ältesten Zeile (wer die Rolle zuerst vergab).
    granted_by: str
    rows: tuple[RoleAssignment, ...] = field(default_factory=tuple[RoleAssignment, ...])

    def as_report(self) -> dict[str, Any]:
        """Der Eintrag in ``rollen_fremd`` — genau diese vier Felder."""
        return {
            "username": self.username,
            "principal": self.principal,
            "role": self.role,
            "granted_by": self.granted_by,
        }


async def _usernames(session: AsyncSession, guids: Sequence[str]) -> dict[str, str]:
    """Name je GUID: das Anmeldekonto zuerst, sonst der UPN der AD-Zeile.

    `# scope-bypass: nur die Namen der Rolleninhaber des ganzen Mandanten, für
    die Meldung an den Betreiber; kein Schul-Scope, die Trennung leistet der
    ``search_path``.`
    """
    if not guids:
        return {}
    out: dict[str, str] = {
        a.principal_guid: a.username
        for a in await LoginAccountRepository(session).list_by_principals(list(guids))
    }
    missing = [g for g in guids if g not in out]
    if missing:
        stmt = select(AdUserCache.ad_object_guid, AdUserCache.upn).where(
            AdUserCache.ad_object_guid.in_(missing)
        )
        for guid, upn in (await session.execute(stmt)).all():
            try:
                out[guid] = validate_login_name(upn)
            except ValueError:
                continue
    return out


def _sort_key(row: RoleAssignment) -> tuple[datetime, int]:
    return (row.granted_at, row.id)


async def foreign_roles(session: AsyncSession, base: Settings) -> list[ForeignRole]:
    """Alle fremden Rollen des Mandanten, sortiert nach Name, Person und Rolle.

    ``bootstrap_admins`` gelten wie bei der Anmeldung: die aus der Konsole
    (``app_settings``) vor denen der Umgebung.
    """
    settings = await load_effective_settings(session, base)
    # scope-bypass: der Abgleich und die Meldung sehen alle Zuweisungen des Mandanten.
    active = await RoleAssignmentRepository(session).list_all_active()
    candidates = [
        r
        for r in active
        if r.granted_by != GRANTED_BY_COCKPIT and r.ad_object_guid != LOCAL_ADMIN_GUID
    ]
    names = await _usernames(session, sorted({r.ad_object_guid for r in candidates}))
    grouped: dict[tuple[str, str], list[RoleAssignment]] = {}
    for row in candidates:
        name = names.get(row.ad_object_guid)
        if (
            row.role == ROLE_ADMIN
            and row.school_id is None
            and name is not None
            and is_bootstrap_admin(settings, name)
        ):
            continue
        grouped.setdefault((row.ad_object_guid, row.role), []).append(row)
    out = [
        ForeignRole(
            principal=principal,
            role=role,
            username=names.get(principal),
            granted_by=(min(rows, key=_sort_key).granted_by or _UNKNOWN_SOURCE),
            rows=tuple(sorted(rows, key=lambda r: (r.school_id or 0, r.id))),
        )
        for (principal, role), rows in grouped.items()
    ]
    out.sort(key=lambda f: (f.username or "", f.principal, f.role))
    return out


async def foreign_roles_report(session: AsyncSession, settings: Settings) -> list[dict[str, Any]]:
    """``rollen_fremd`` für die Zustandsmeldung, höchstens :data:`FOREIGN_ROLES_MAX`."""
    found = await foreign_roles(session, settings)
    if len(found) > FOREIGN_ROLES_MAX:
        logger.warning(
            "%d fremde Rollen, die Zustandsmeldung trägt die ersten %d.",
            len(found),
            FOREIGN_ROLES_MAX,
        )
    return [f.as_report() for f in found[:FOREIGN_ROLES_MAX]]


@dataclass(frozen=True)
class RevokedForeignRole:
    """Eine entzogene Zeile, für Ergebnis, Log und Audit."""

    principal: str
    role: str
    school_id: int | None
    username: str | None
    granted_by: str | None


class ForeignRoleRevoker:
    """Entzieht fremde Rollen auf Wunsch des Cockpits (``role_revocations``)."""

    def __init__(
        self,
        session: AsyncSession,
        settings: Settings,
        *,
        actor: str,
        request_id: str,
        tenant_slug: str,
    ) -> None:
        self.session = session
        self.settings = settings
        self.actor = actor
        self.request_id = request_id[:36]
        self.tenant_slug = tenant_slug

    async def _foreign(self) -> dict[tuple[str, str], ForeignRole]:
        return {
            (f.principal.lower(), f.role): f
            for f in await foreign_roles(self.session, self.settings)
        }

    async def revoke(
        self, wanted: Sequence[DesiredRoleRevocation], *, dry_run: bool = False
    ) -> tuple[list[RevokedForeignRole], list[str]]:
        """Entziehen; zurück kommen die entzogenen Zeilen und die übergangenen Einträge.

        Übergangen (nur im Log, kein Fehler) wird ein Eintrag, zu dem es keine
        fremde Rolle gibt — schon entzogen, nie vorhanden oder nicht fremd. Das
        Cockpit sendet die Liste, bis die Meldung die Rolle nicht mehr nennt;
        ein zweiter Lauf findet nichts mehr und schreibt nichts.
        """
        if not wanted:
            return [], []
        found = await self._foreign()
        if not dry_run and any((e.principal, e.role) in found for e in wanted):
            # Zwei Container gleichen denselben Kunden ab: dieselbe Sperre wie
            # die Rollenliste (ADR-0026 D3), und unter ihr neu gelesen — sonst
            # entzögen beide dieselbe Zeile und schrieben das Audit doppelt.
            await self.session.execute(
                text("SELECT pg_advisory_xact_lock(hashtext(:k))"),
                {"k": f"cockpit-roles:{self.tenant_slug}"},
            )
            found = await self._foreign()
        revoked: list[RevokedForeignRole] = []
        unmatched: list[str] = []
        repo = RoleAssignmentRepository(self.session)
        audit = AuditService(self.session, self.settings)
        for entry in wanted:
            foreign = found.get((entry.principal, entry.role))
            if foreign is None:
                unmatched.append(f"{entry.principal}:{entry.role}")
                continue
            for row in foreign.rows:
                change = RevokedForeignRole(
                    principal=foreign.principal,
                    role=foreign.role,
                    school_id=row.school_id,
                    username=foreign.username,
                    granted_by=row.granted_by,
                )
                if dry_run:
                    revoked.append(change)
                    continue
                done = await repo.revoke(
                    ad_object_guid=row.ad_object_guid, role=row.role, school_id=row.school_id
                )
                if done is None:
                    continue
                await audit.emit(
                    action="role_revoked",
                    target_kind="role_assignment",
                    target_id=change.principal,
                    actor_upn=self.actor,
                    actor_object_guid=None,
                    school_id=change.school_id,
                    ip=None,
                    request_id=self.request_id,
                    payload={
                        "role": change.role,
                        "school_id": change.school_id,
                        "username": change.username,
                        "granted_by": change.granted_by,
                        "via": VIA_COCKPIT_REVOCATION,
                    },
                )
                revoked.append(change)
        return revoked, unmatched


__all__ = [
    "FOREIGN_ROLES_MAX",
    "VIA_COCKPIT_REVOCATION",
    "ForeignRole",
    "ForeignRoleRevoker",
    "RevokedForeignRole",
    "foreign_roles",
    "foreign_roles_report",
]
