"""Rollen aus dem Cockpit abgleichen (ADR-0026).

Das Cockpit führt je Kunde eine Liste Keycloak-Benutzer → Rolle, und die Rolle
gilt für den **ganzen Kunden**. Die Einheiten sieht das Cockpit nicht; hier wird
daraus, was in ``role_assignments`` stehen soll:

* ``admin`` → eine Zuweisung ohne Einheit (``school_id`` NULL);
* ``schulleitung`` und ``smi`` → eine Zuweisung an **jeder** Einheit
  (``schools``). Kommt eine Einheit dazu, ergänzt der nächste Abgleich.

Die Herkunft steht in ``granted_by`` (:data:`GRANTED_BY_COCKPIT`).
Zurückgenommen wird nur, was diese Herkunft hat. Eine Zuweisung, die von Hand
oder per Bootstrap schon besteht, wird weder doppelt angelegt noch übernommen
noch entzogen.

Personen sind Anmeldekonten (ADR-0025). Fehlt eines, wird es vorab angelegt und
bindet bei der ersten Anmeldung. Hält schon ein anderes Konto die GUID, wird der
Eintrag ausgelassen und gemeldet; der Rest läuft weiter.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass, field

from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from magister_api.audit.service import AuditService
from magister_api.auth.roles import GRANTED_BY_COCKPIT
from magister_api.config import Settings
from magister_api.models.school import School
from magister_api.repositories.auth import LoginAccountRepository, RoleAssignmentRepository
from magister_api.services.login_accounts import LoginAccountConflictError, LoginAccountService
from magister_api.services.rbac import RbacService
from magister_api.tenancy.desired_state import DesiredRoleAssignment

logger = logging.getLogger(__name__)

#: (principal_guid, Rolle, Einheit) — eine Zeile in ``role_assignments``.
Triple = tuple[str, str, int | None]


@dataclass(frozen=True)
class RoleAssignmentChange:
    """Eine vergebene oder zurückgenommene Zuweisung, für Ergebnis und Log."""

    #: Benutzername des Kontos; ohne Konto die GUID.
    username: str
    principal_guid: str
    role: str
    school_id: int | None

    @property
    def label(self) -> str:
        where = "alle" if self.school_id is None else f"#{self.school_id}"
        return f"{self.username}:{self.role}@{where}"


@dataclass
class CockpitRolesOutcome:
    """Was der Abgleich der Rollen getan hat (bei ``dry_run``: tun würde)."""

    granted: list[RoleAssignmentChange] = field(default_factory=list[RoleAssignmentChange])
    revoked: list[RoleAssignmentChange] = field(default_factory=list[RoleAssignmentChange])
    #: Vorab angelegte Anmeldekonten (Benutzernamen).
    created_accounts: list[str] = field(default_factory=list[str])
    #: {benutzer: Grund} — Einträge, die ausgelassen wurden.
    skipped: dict[str, str] = field(default_factory=dict[str, str])

    @property
    def touched(self) -> bool:
        return bool(self.granted or self.revoked or self.created_accounts)


@dataclass
class _Plan:
    #: Fehlende Konten: {benutzer: principal_guid}.
    create: dict[str, str] = field(default_factory=dict[str, str])
    #: Gewollte Zuweisungen: {tripel: benutzer}.
    wanted: dict[Triple, str] = field(default_factory=dict[Triple, str])
    grant: list[RoleAssignmentChange] = field(default_factory=list[RoleAssignmentChange])
    revoke: list[RoleAssignmentChange] = field(default_factory=list[RoleAssignmentChange])
    skipped: dict[str, str] = field(default_factory=dict[str, str])

    @property
    def empty(self) -> bool:
        return not (self.create or self.grant or self.revoke)

    def outcome(self) -> CockpitRolesOutcome:
        return CockpitRolesOutcome(
            granted=list(self.grant),
            revoked=list(self.revoke),
            created_accounts=sorted(self.create),
            skipped=dict(self.skipped),
        )


def _order(change: RoleAssignmentChange) -> tuple[str, str, int]:
    return (change.username, change.role, change.school_id or 0)


class CockpitRoleSync:
    """Die Rollenliste des Cockpits in ``role_assignments`` abgleichen."""

    def __init__(
        self, session: AsyncSession, settings: Settings, *, actor: str, request_id: str
    ) -> None:
        self.session = session
        self.settings = settings
        self.actor = actor
        self.request_id = request_id[:36]

    async def reconcile(
        self,
        entries: Sequence[DesiredRoleAssignment],
        *,
        tenant_slug: str,
        dry_run: bool = False,
    ) -> CockpitRolesOutcome:
        plan = await self._plan(entries)
        if dry_run or plan.empty:
            return plan.outcome()
        # Zwei Container gleichen denselben Kunden ab. Gesperrt wird erst, wenn
        # es etwas zu tun gibt (der Normalfall ist: nichts), und unter der
        # Sperre wird neu geplant — so findet der zweite Container, was der
        # erste schon geschrieben hat, statt es ein zweites Mal anzulegen.
        await self.session.execute(
            text("SELECT pg_advisory_xact_lock(hashtext(:k))"),
            {"k": f"cockpit-roles:{tenant_slug}"},
        )
        return await self._apply(await self._plan(entries))

    async def _school_ids(self) -> list[int]:
        """Alle Einheiten des Mandanten.

        `# scope-bypass: nur die Ids der Einheiten, keine Personendaten; die
        Mandantentrennung leistet der ``search_path`` dieser Sitzung.`
        """
        rows = await self.session.execute(select(School.id).order_by(School.id))
        return [int(r) for r in rows.scalars().all()]

    async def _plan(self, entries: Sequence[DesiredRoleAssignment]) -> _Plan:
        """Lesen und vergleichen, ohne zu schreiben."""
        plan = _Plan()
        accounts = LoginAccountRepository(self.session)
        catalog = {r.key: r for r in await RbacService(self.session).list_roles()}
        schools = await self._school_ids()
        principals: dict[str, str] = {}

        for entry in entries:
            role_def = catalog.get(entry.role)
            if role_def is None or role_def.is_derived:
                plan.skipped[f"{entry.username}:{entry.role}"] = "role_not_found"
                continue
            if entry.username in plan.skipped:
                continue
            principal = principals.get(entry.username)
            if principal is None:
                account = await accounts.get_by_username(entry.username)
                if account is not None:
                    principal = account.principal_guid
                else:
                    principal = await LoginAccountService(
                        self.session, self.settings
                    ).principal_for(entry.username)
                    if await accounts.get_by_principal(principal) is not None:
                        # Dieselbe Person unter anderem Namen, oder ein in
                        # Keycloak umbenannter Benutzer, der sich seither nicht
                        # angemeldet hat: welches Konto gilt, entscheidet ein
                        # Mensch (ADR-0025 D2), nicht der Abgleich.
                        plan.skipped[entry.username] = "account_principal_conflict"
                        continue
                    plan.create[entry.username] = principal
                principals[entry.username] = principal
            units: list[int | None] = [None] if role_def.is_admin else list(schools)
            for school_id in units:
                plan.wanted.setdefault((principal, entry.role, school_id), entry.username)

        # scope-bypass: der Abgleich vergleicht alle Zuweisungen des Mandanten.
        active = await RoleAssignmentRepository(self.session).list_all_active()
        have: set[Triple] = {(r.ad_object_guid, r.role, r.school_id) for r in active}
        for triple, username in plan.wanted.items():
            if triple not in have:
                # Auch wenn dieselbe Zuweisung aus anderer Quelle besteht, wird
                # nichts angelegt: `have` kennt jede Herkunft.
                plan.grant.append(RoleAssignmentChange(username, *triple))

        gone = [
            r
            for r in active
            if r.granted_by == GRANTED_BY_COCKPIT
            and (r.ad_object_guid, r.role, r.school_id) not in plan.wanted
        ]
        holders = await accounts.list_by_principals(sorted({r.ad_object_guid for r in gone}))
        names = {a.principal_guid: a.username for a in holders}
        for r in gone:
            plan.revoke.append(
                RoleAssignmentChange(
                    names.get(r.ad_object_guid, r.ad_object_guid),
                    r.ad_object_guid,
                    r.role,
                    r.school_id,
                )
            )
        plan.grant.sort(key=_order)
        plan.revoke.sort(key=_order)
        return plan

    async def _apply(self, plan: _Plan) -> CockpitRolesOutcome:
        out = CockpitRolesOutcome(skipped=dict(plan.skipped))
        audit = AuditService(self.session, self.settings)
        repo = RoleAssignmentRepository(self.session)
        dropped: set[str] = set()

        for username, principal in sorted(plan.create.items()):
            try:
                # Ein Savepoint je Konto: ein Konflikt nimmt weder die übrigen
                # Konten noch den Rest des Abgleichs mit.
                async with self.session.begin_nested():
                    account = await LoginAccountService(self.session, self.settings).precreate(
                        username=username, display_name=None
                    )
            except LoginAccountConflictError as exc:
                out.skipped[username] = exc.code
                dropped.add(principal)
                continue
            except IntegrityError:
                out.skipped[username] = "login_account_conflict"
                dropped.add(principal)
                continue
            out.created_accounts.append(username)
            await audit.emit(
                action="login_account_created",
                target_kind="login_account",
                target_id=str(account.id),
                actor_upn=self.actor,
                actor_object_guid=None,
                school_id=None,
                ip=None,
                request_id=self.request_id,
                payload={
                    "username": username,
                    "principal_guid": account.principal_guid,
                    "via": "cockpit",
                },
            )

        for change in plan.grant:
            if change.principal_guid in dropped:
                continue
            await repo.grant(
                ad_object_guid=change.principal_guid,
                role=change.role,
                school_id=change.school_id,
                granted_by=GRANTED_BY_COCKPIT,
            )
            await self._emit(audit, "role_granted", change)
            out.granted.append(change)

        for change in plan.revoke:
            row = await repo.revoke(
                ad_object_guid=change.principal_guid,
                role=change.role,
                school_id=change.school_id,
            )
            if row is None:
                continue
            await self._emit(audit, "role_revoked", change)
            out.revoked.append(change)
        return out

    async def _emit(self, audit: AuditService, action: str, change: RoleAssignmentChange) -> None:
        await audit.emit(
            action=action,
            target_kind="role_assignment",
            target_id=change.principal_guid,
            actor_upn=self.actor,
            actor_object_guid=None,
            school_id=change.school_id,
            ip=None,
            request_id=self.request_id,
            payload={
                "role": change.role,
                "school_id": change.school_id,
                "username": change.username,
                "via": "cockpit",
            },
        )


__all__ = ["CockpitRoleSync", "CockpitRolesOutcome", "RoleAssignmentChange"]
