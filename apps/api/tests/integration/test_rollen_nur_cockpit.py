"""Rollen nur aus dem Cockpit gegen eine echte Datenbank (ADR-0027).

Die Zusagen:

* Führt das Cockpit die Rollen (``role_assignments`` ≠ ``null``), lehnt die API
  Vergeben, Entziehen, Konten vorab anlegen, Bindung lösen und Konten löschen
  mit 409 ab; lesen, sperren und freigeben bleiben. Das lokale
  Administrationskonto (Notzugang) ist ausgenommen.
* Sagt das Cockpit nichts mehr (``null``), geht die Vergabe von Hand wieder.
* Die Zustandsmeldung trägt ``rollen_fremd``: Rollen aus anderer Quelle, je
  Person und Rolle ein Eintrag, ohne Notzugang, ohne Zuweisungen aus dem
  Cockpit und ohne die Admin-Rolle der ersten Administratoren der Konsole.
* ``role_revocations`` entzieht nur solche fremden Rollen, an allen Einheiten,
  auditiert; ein zweiter Lauf tut nichts.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from pydantic import BaseModel, ValidationError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from magister_api.audit.service import AuditService
from magister_api.auth.csrf import issue_csrf_token
from magister_api.auth.role_lock import ROLES_MANAGED_BY_COCKPIT
from magister_api.config import Settings
from magister_api.models.audit import AuditEvent
from magister_api.models.auth import AdUserCache, LoginAccount, RoleAssignment, Session
from magister_api.models.base import utcnow
from magister_api.services.foreign_roles import FOREIGN_ROLES_MAX, VIA_COCKPIT_REVOCATION
from magister_api.services.local_admin import LOCAL_ADMIN_GUID
from magister_api.services.login_accounts import synthetic_principal
from magister_api.services.reconciler import Reconciler, ReconcileResult
from magister_api.services.role_lock import ROLES_SOURCE_EVENT, roles_from_cockpit
from magister_api.tenancy.desired_state import (
    DesiredRoleAssignment,
    DesiredRoleRevocation,
    DesiredState,
)
from magister_api.tenancy.registry import Tenant
from magister_api.tenancy.status_report import collect_status, reconcile_outcome
from tests.konsole import konsole_modul

pytestmark = pytest.mark.postgres

IT = "it@example.ch"
ANNA = "anna"
ISSUER = "https://sso.example.ch/realms/kunde-a"


def _desired(
    *pairs: tuple[str, str],
    revoke: tuple[tuple[str, str], ...] = (),
    lead: bool = True,
) -> DesiredState:
    return DesiredState(
        role_assignments=(
            tuple(DesiredRoleAssignment(username=u, role=r) for u, r in pairs) if lead else None
        ),
        role_revocations=tuple(DesiredRoleRevocation(principal=p, role=r) for p, r in revoke),
    )


async def _reconcile(
    session: AsyncSession, settings: Settings, desired: DesiredState, *, dry_run: bool = False
) -> ReconcileResult:
    result = await Reconciler(session, settings).reconcile(
        desired, tenant_slug="kunde-a", dry_run=dry_run
    )
    await session.commit()
    return result


async def _active(session: AsyncSession) -> set[tuple[str, str, int | None, str | None]]:
    stmt = select(RoleAssignment).where(RoleAssignment.revoked_at.is_(None))
    rows = (await session.execute(stmt)).scalars().all()
    return {(r.ad_object_guid, r.role, r.school_id, r.granted_by) for r in rows}


async def _count(session: AsyncSession, action: str) -> int:
    stmt = select(func.count()).select_from(AuditEvent).where(AuditEvent.action == action)
    return (await session.execute(stmt)).scalar_one()


async def _payloads(session: AsyncSession, settings: Settings, action: str) -> list[dict[str, Any]]:
    stmt = select(AuditEvent.id).where(AuditEvent.action == action).order_by(AuditEvent.id)
    audit = AuditService(session, settings)
    out: list[dict[str, Any]] = []
    for event_id in (await session.execute(stmt)).scalars().all():
        record = await audit.read(event_id)
        assert record is not None
        out.append(dict(record.payload))
    return out


def _grant(
    session: AsyncSession,
    guid: str,
    role: str,
    school_id: int | None,
    granted_by: str | None,
    *,
    minutes_ago: int = 0,
) -> None:
    session.add(
        RoleAssignment(
            ad_object_guid=guid,
            role=role,
            school_id=school_id,
            granted_by=granted_by,
            granted_at=utcnow() - timedelta(minutes=minutes_ago),
        )
    )


def _tenant(app_settings: Settings) -> Tenant:
    return Tenant(
        slug="kunde-a",
        name="Kunde A",
        dsn=app_settings.database_url,
        schema_name="public",
        db_role=None,
        schema_version="x",
        console_id="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
    )


async def _report(session: AsyncSession, settings: Settings) -> dict[str, Any]:
    report = await collect_status(
        session, settings, _tenant(settings), reconcile=reconcile_outcome(ok=True)
    )
    await session.rollback()
    return report


async def _local_admin_client(
    app: FastAPI, session: AsyncSession, settings: Settings
) -> AsyncClient:
    """Eine Sitzung des lokalen Administrationskontos (Notzugang), wie nach dem Anmelden."""
    now = utcnow()
    session.add(
        AdUserCache(
            ad_object_guid=LOCAL_ADMIN_GUID,
            school_id=None,
            upn="admin@magister.local",
            kind="admin",
            enabled=True,
        )
    )
    _grant(session, LOCAL_ADMIN_GUID, "admin", None, "bootstrap")
    session.add(
        Session(
            id="sid-notzugang",
            ad_object_guid=LOCAL_ADMIN_GUID,
            oidc_subject="",  # keine OIDC-Sitzung, wie beim Anmelden
            auth_kind="local",
            expires_at=now + timedelta(hours=1),
            last_seen_at=now,
            created_at=now,
        )
    )
    await session.commit()
    csrf = issue_csrf_token("sid-notzugang", settings)
    return AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
        cookies={"magister_session": "sid-notzugang", "magister_csrf": csrf},
        headers={"X-CSRF-Token": csrf},
    )


def _refused(response: Any) -> None:
    assert response.status_code == 409, response.text
    assert response.json()["detail"] == ROLES_MANAGED_BY_COCKPIT


class TestTheFlag:
    async def test_it_follows_the_desired_state_and_is_audited_on_change(
        self, db_session: AsyncSession, app_settings: Settings
    ) -> None:
        assert not await roles_from_cockpit(db_session)

        first = await _reconcile(db_session, app_settings, _desired())
        again = await _reconcile(db_session, app_settings, _desired())
        assert first.roles_source_changed and await roles_from_cockpit(db_session)
        assert not again.touched

        gone = await _reconcile(db_session, app_settings, _desired(lead=False))
        assert gone.roles_source_changed and not await roles_from_cockpit(db_session)
        assert await _payloads(db_session, app_settings, ROLES_SOURCE_EVENT) == [
            {"from_cockpit": True},
            {"from_cockpit": False},
        ]

    async def test_dry_run_leaves_it(
        self, db_session: AsyncSession, app_settings: Settings
    ) -> None:
        result = await _reconcile(db_session, app_settings, _desired(), dry_run=True)
        assert not result.roles_source_changed
        assert not await roles_from_cockpit(db_session)


class TestApiRefuses:
    async def test_grant_set_and_revoke_are_refused(
        self,
        as_admin: AsyncClient,
        db_session: AsyncSession,
        app_settings: Settings,
        school_a: int,
    ) -> None:
        guid = synthetic_principal(ANNA)
        db_session.add(LoginAccount(username=ANNA, principal_guid=guid))
        _grant(db_session, guid, "smi", school_a, "admin@example.ch")
        await db_session.commit()
        await _reconcile(db_session, app_settings, _desired())
        before = await _active(db_session)
        granted, revoked = (
            await _count(db_session, "role_granted"),
            await _count(db_session, "role_revoked"),
        )

        _refused(
            await as_admin.post(
                f"/admin/users/{guid}/roles", json={"role": "schulleitung", "school_id": school_a}
            )
        )
        _refused(await as_admin.put(f"/admin/users/{guid}/roles", json={"assignments": []}))
        _refused(
            await as_admin.delete(
                f"/admin/users/{guid}/roles", params={"role": "smi", "school_id": school_a}
            )
        )
        # Die Sperre kommt vor der Prüfung des Inhalts: auch Unsinn wird mit 409 abgelehnt.
        _refused(await as_admin.post(f"/admin/users/{guid}/roles", json={"role": ""}))

        assert await _active(db_session) == before
        assert await _count(db_session, "role_granted") == granted
        assert await _count(db_session, "role_revoked") == revoked

    async def test_reading_stays(
        self, as_admin: AsyncClient, db_session: AsyncSession, app_settings: Settings
    ) -> None:
        await _reconcile(db_session, app_settings, _desired((IT, "admin")))

        roles = await as_admin.get("/admin/roles")
        accounts = await as_admin.get("/admin/login-accounts")

        assert roles.status_code == 200 and accounts.status_code == 200
        assert {(a["upn"], a["from_cockpit"]) for a in roles.json()} >= {(IT, True)}
        assert IT in {a["username"] for a in accounts.json()}

    async def test_the_source_says_who_leads(
        self, as_admin: AsyncClient, db_session: AsyncSession, app_settings: Settings
    ) -> None:
        before = (await as_admin.get("/admin/roles/source")).json()
        await _reconcile(db_session, app_settings, _desired())
        after = (await as_admin.get("/admin/roles/source")).json()

        assert before == {"from_cockpit": False, "editable": True, "emergency_access": False}
        assert after == {"from_cockpit": True, "editable": False, "emergency_access": False}

    async def test_login_accounts_are_neither_created_nor_unbound_nor_deleted(
        self, as_admin: AsyncClient, db_session: AsyncSession, app_settings: Settings
    ) -> None:
        bert = LoginAccount(
            username="bert", principal_guid=synthetic_principal("bert"), issuer=ISSUER, subject="s"
        )
        db_session.add(bert)
        await db_session.commit()
        await _reconcile(db_session, app_settings, _desired())

        _refused(await as_admin.post("/admin/login-accounts", json={"username": "neu"}))
        _refused(await as_admin.post(f"/admin/login-accounts/{bert.id}/unbind"))
        _refused(await as_admin.delete(f"/admin/login-accounts/{bert.id}"))

        await db_session.refresh(bert)
        assert bert.subject == "s"
        assert (
            await db_session.execute(select(LoginAccount).where(LoginAccount.username == "neu"))
        ).scalar_one_or_none() is None

    async def test_disabling_and_enabling_stay(
        self, as_admin: AsyncClient, db_session: AsyncSession, app_settings: Settings
    ) -> None:
        """Sperren gibt niemandem Rechte und ist der schnelle Griff bei einem Vorfall."""
        await _reconcile(db_session, app_settings, _desired(("bert", "admin")))
        account_id = (
            await db_session.execute(select(LoginAccount.id).where(LoginAccount.username == "bert"))
        ).scalar_one()

        off = await as_admin.patch(f"/admin/login-accounts/{account_id}", json={"enabled": False})
        on = await as_admin.patch(f"/admin/login-accounts/{account_id}", json={"enabled": True})

        assert (off.status_code, off.json()["enabled"]) == (200, False)
        assert (on.status_code, on.json()["enabled"]) == (200, True)

    async def test_without_the_right_it_stays_403(
        self, as_schulleitung_a: AsyncClient, db_session: AsyncSession, app_settings: Settings
    ) -> None:
        """Die Sperre verrät niemandem ohne Admin-Recht, wer die Rollen führt."""
        await _reconcile(db_session, app_settings, _desired())
        resp = await as_schulleitung_a.put(
            f"/admin/users/{synthetic_principal(ANNA)}/roles", json={"assignments": []}
        )
        assert resp.status_code == 403

    async def test_without_the_cockpit_hand_grants_work(
        self, as_admin: AsyncClient, db_session: AsyncSession, school_a: int
    ) -> None:
        created = await as_admin.post("/admin/login-accounts", json={"username": ANNA})
        guid = created.json()["principal_guid"]
        resp = await as_admin.post(
            f"/admin/users/{guid}/roles", json={"role": "smi", "school_id": school_a}
        )
        assert (created.status_code, resp.status_code) == (201, 201)

    async def test_when_the_cockpit_gives_up_hand_grants_work_again(
        self,
        as_admin: AsyncClient,
        db_session: AsyncSession,
        app_settings: Settings,
        school_a: int,
    ) -> None:
        await _reconcile(db_session, app_settings, _desired((ANNA, "admin")))
        guid = synthetic_principal(ANNA)
        body = {"role": "smi", "school_id": school_a}
        _refused(await as_admin.post(f"/admin/users/{guid}/roles", json=body))

        await _reconcile(db_session, app_settings, _desired(lead=False))

        assert (await as_admin.post(f"/admin/users/{guid}/roles", json=body)).status_code == 201


class TestEmergencyAccess:
    async def test_the_local_admin_may_still_grant_and_it_counts_as_foreign(
        self,
        app: FastAPI,
        db_session: AsyncSession,
        app_settings: Settings,
        school_a: int,
    ) -> None:
        await _reconcile(db_session, app_settings, _desired((ANNA, "admin")))
        guid = synthetic_principal(ANNA)

        async with await _local_admin_client(app, db_session, app_settings) as notzugang:
            source = (await notzugang.get("/admin/roles/source")).json()
            resp = await notzugang.post(
                f"/admin/users/{guid}/roles", json={"role": "smi", "school_id": school_a}
            )
            created = await notzugang.post("/admin/login-accounts", json={"username": "notfall"})

        assert source == {"from_cockpit": True, "editable": True, "emergency_access": True}
        assert resp.status_code == 201, resp.text
        assert created.status_code == 201, created.text
        # Was der Notzugang vergibt, sieht das Cockpit als fremde Rolle.
        report = await _report(db_session, app_settings)
        assert report["rollen_fremd"] == [
            {
                "username": ANNA,
                "principal": guid,
                "role": "smi",
                "granted_by": "admin@magister.local",
            }
        ]


class TestForeignRolesReport:
    async def test_only_foreign_roles_are_reported(
        self,
        db_session: AsyncSession,
        app_settings: Settings,
        school_a: int,
        school_b: int,
    ) -> None:
        await _reconcile(db_session, app_settings, _desired((IT, "smi")))
        anna = synthetic_principal(ANNA)
        db_session.add(LoginAccount(username=ANNA, principal_guid=anna))
        # Zwei Einheiten, zwei Quellen: ein Eintrag, die ältere Herkunft.
        _grant(db_session, anna, "schulleitung", school_b, "zweite@example.ch", minutes_ago=5)
        _grant(db_session, anna, "schulleitung", school_a, "admin@example.ch", minutes_ago=60)
        # Eine Person aus dem AD ohne Anmeldekonto: ihr UPN, klein.
        lehrer = "11111111-2222-3333-4444-555555555555"
        db_session.add(
            AdUserCache(
                ad_object_guid=lehrer,
                school_id=school_a,
                upn="Lehrer.X@Example.ch",
                kind="teacher",
                enabled=True,
            )
        )
        _grant(db_session, lehrer, "smi", school_a, "admin@example.ch")
        # Ohne Konto und ohne AD-Zeile: kein Name, Herkunft unbekannt.
        niemand = "99999999-8888-7777-6666-555555555555"
        _grant(db_session, niemand, "admin", None, None)
        # Der Notzugang und ein erster Administrator der Konsole: nicht fremd.
        _grant(db_session, LOCAL_ADMIN_GUID, "admin", None, "bootstrap")
        automato = synthetic_principal("automato-admin")
        db_session.add(LoginAccount(username="automato-admin", principal_guid=automato))
        _grant(db_session, automato, "admin", None, "bootstrap")
        # Ein ehemaliger erster Administrator (nicht mehr in bootstrap_admins): fremd.
        ehemals = synthetic_principal("ehemals")
        db_session.add(LoginAccount(username="ehemals", principal_guid=ehemals))
        _grant(db_session, ehemals, "admin", None, "bootstrap")
        # Zurückgenommen: nicht mehr da.
        weg = synthetic_principal("weg")
        db_session.add(
            RoleAssignment(
                ad_object_guid=weg,
                role="smi",
                school_id=school_a,
                granted_by="admin@example.ch",
                revoked_at=utcnow(),
            )
        )
        await db_session.commit()

        report = await _report(db_session, app_settings)

        assert report["rollen_fremd"] == [
            {"username": None, "principal": niemand, "role": "admin", "granted_by": "unbekannt"},
            {
                "username": ANNA,
                "principal": anna,
                "role": "schulleitung",
                "granted_by": "admin@example.ch",
            },
            {
                "username": "ehemals",
                "principal": ehemals,
                "role": "admin",
                "granted_by": "bootstrap",
            },
            {
                "username": "lehrer.x@example.ch",
                "principal": lehrer,
                "role": "smi",
                "granted_by": "admin@example.ch",
            },
        ]

    async def test_without_the_cockpit_there_is_no_field(
        self, db_session: AsyncSession, app_settings: Settings, school_a: int
    ) -> None:
        _grant(db_session, synthetic_principal(ANNA), "smi", school_a, "admin@example.ch")
        await db_session.commit()
        assert "rollen_fremd" not in await _report(db_session, app_settings)

        await _reconcile(db_session, app_settings, _desired())
        assert len((await _report(db_session, app_settings))["rollen_fremd"]) == 1

        await _reconcile(db_session, app_settings, _desired(lead=False))
        assert "rollen_fremd" not in await _report(db_session, app_settings)

    async def test_at_most_200_entries(
        self, db_session: AsyncSession, app_settings: Settings, school_a: int
    ) -> None:
        for i in range(FOREIGN_ROLES_MAX + 5):
            _grant(db_session, synthetic_principal(f"person-{i:03d}"), "smi", school_a, "x")
        await db_session.commit()
        await _reconcile(db_session, app_settings, _desired())

        report = await _report(db_session, app_settings)

        assert len(report["rollen_fremd"]) == FOREIGN_ROLES_MAX


def _cockpit_status_report() -> type[BaseModel]:
    """`StatusReport` des Cockpits, aus seiner Datei (`schemas/operations.py`)."""
    module = konsole_modul("schemas", "operations.py", name="console_operations_rollen")
    model: type[BaseModel] = module.StatusReport
    return model


class TestStatusReportMatchesTheCockpit:
    """Gleichlauf mit dem Cockpit für ``rollen_fremd`` (prüft streng, ``extra=forbid``)."""

    async def _with_foreign(
        self, session: AsyncSession, settings: Settings, school: int
    ) -> dict[str, Any]:
        _grant(session, synthetic_principal(ANNA), "smi", school, "admin@example.ch")
        _grant(session, "99999999-8888-7777-6666-555555555555", "admin", None, None)
        await session.commit()
        await _reconcile(session, settings, _desired())
        report = await _report(session, settings)
        assert len(report["rollen_fremd"]) == 2
        return report

    async def test_an_older_cockpit_rejects_the_field_and_takes_the_rest(
        self, db_session: AsyncSession, app_settings: Settings, school_a: int
    ) -> None:
        """Die Voraussetzung für den Rückfall: ohne `rollen_fremd` nimmt es die Meldung an."""
        model = _cockpit_status_report()
        report = await self._with_foreign(db_session, app_settings, school_a)
        model.model_validate({k: v for k, v in report.items() if k != "rollen_fremd"})
        if "rollen_fremd" in model.model_fields:
            pytest.skip("Das Cockpit kennt `rollen_fremd` schon.")
        with pytest.raises(ValidationError, match="rollen_fremd"):
            model.model_validate(report)

    async def test_the_report_with_the_field_is_accepted(
        self, db_session: AsyncSession, app_settings: Settings, school_a: int
    ) -> None:
        model = _cockpit_status_report()
        if "rollen_fremd" not in model.model_fields:
            pytest.skip("Das Cockpit kennt das Feld `rollen_fremd` der Zustandsmeldung noch nicht.")
        report = await self._with_foreign(db_session, app_settings, school_a)
        back = model.model_validate(report).model_dump(mode="json")["rollen_fremd"]
        assert [set(e) for e in back] == [{"username", "principal", "role", "granted_by"}] * 2
        assert [(e["principal"], e["role"]) for e in back] == [
            (e["principal"], e["role"]) for e in report["rollen_fremd"]
        ]


class TestRevocations:
    async def test_only_foreign_roles_are_revoked_at_every_unit(
        self,
        db_session: AsyncSession,
        app_settings: Settings,
        school_a: int,
        school_b: int,
    ) -> None:
        anna = synthetic_principal(ANNA)
        db_session.add(LoginAccount(username=ANNA, principal_guid=anna))
        _grant(db_session, anna, "schulleitung", school_a, "admin@example.ch")
        _grant(db_session, anna, "schulleitung", school_b, "admin@example.ch")
        _grant(db_session, anna, "smi", school_a, "admin@example.ch")
        _grant(db_session, LOCAL_ADMIN_GUID, "admin", None, "bootstrap")
        automato = synthetic_principal("automato-admin")
        db_session.add(LoginAccount(username="automato-admin", principal_guid=automato))
        _grant(db_session, automato, "admin", None, "bootstrap")
        await db_session.commit()
        await _reconcile(db_session, app_settings, _desired((IT, "smi")))
        it = synthetic_principal(IT)

        desired = _desired(
            (IT, "smi"),
            revoke=(
                (anna, "schulleitung"),
                # nicht fremd: aus dem Cockpit, Notzugang, erster Administrator
                (it, "smi"),
                (LOCAL_ADMIN_GUID, "admin"),
                (automato, "admin"),
                # gibt es nicht
                ("99999999-8888-7777-6666-555555555555", "admin"),
            ),
        )
        result = await _reconcile(db_session, app_settings, desired)

        assert {(c.principal, c.role, c.school_id) for c in result.revoked_foreign} == {
            (anna, "schulleitung", school_a),
            (anna, "schulleitung", school_b),
        }
        assert await _active(db_session) == {
            (anna, "smi", school_a, "admin@example.ch"),
            (it, "smi", school_a, "cockpit"),
            (it, "smi", school_b, "cockpit"),
            (LOCAL_ADMIN_GUID, "admin", None, "bootstrap"),
            (automato, "admin", None, "bootstrap"),
        }
        revoked = await _payloads(db_session, app_settings, "role_revoked")
        assert sorted(p["school_id"] for p in revoked) == sorted([school_a, school_b])
        assert {(p["role"], p["username"], p["granted_by"], p["via"]) for p in revoked} == {
            ("schulleitung", ANNA, "admin@example.ch", VIA_COCKPIT_REVOCATION)
        }

        # Das Cockpit sendet den Entzug, bis die Meldung ihn nicht mehr nennt:
        # der zweite Lauf findet nichts mehr und schreibt nichts.
        events = await _count(db_session, "role_revoked")
        again = await _reconcile(db_session, app_settings, desired)
        assert not again.touched
        assert await _count(db_session, "role_revoked") == events

    async def test_principal_case_does_not_matter(
        self, db_session: AsyncSession, app_settings: Settings, school_a: int
    ) -> None:
        """Der Parser schreibt die GUID klein; eine ältere Zeile kann sie gross tragen."""
        lehrer = "ABCDEF00-2222-3333-4444-555555555555"
        _grant(db_session, lehrer, "smi", school_a, "admin@example.ch")
        await db_session.commit()

        result = await _reconcile(
            db_session, app_settings, _desired(revoke=((lehrer.lower(), "smi"),))
        )

        assert [c.principal for c in result.revoked_foreign] == [lehrer]
        assert await _active(db_session) == set()

    async def test_nothing_is_revoked_while_the_cockpit_does_not_lead(
        self, db_session: AsyncSession, app_settings: Settings, school_a: int
    ) -> None:
        anna = synthetic_principal(ANNA)
        _grant(db_session, anna, "smi", school_a, "admin@example.ch")
        await db_session.commit()

        result = await _reconcile(
            db_session, app_settings, _desired(revoke=((anna, "smi"),), lead=False)
        )

        assert result.revoked_foreign == []
        assert await _active(db_session) == {(anna, "smi", school_a, "admin@example.ch")}

    async def test_revoked_and_listed_goes_over_to_the_cockpit(
        self, db_session: AsyncSession, app_settings: Settings, school_a: int
    ) -> None:
        """Entzieht das Cockpit eine fremde Rolle, die es selbst nennt, übernimmt es sie."""
        it = synthetic_principal(IT)
        db_session.add(LoginAccount(username=IT, principal_guid=it))
        _grant(db_session, it, "smi", school_a, "admin@example.ch")
        await db_session.commit()
        await _reconcile(db_session, app_settings, _desired((IT, "smi")))
        assert len((await _report(db_session, app_settings))["rollen_fremd"]) == 1

        result = await _reconcile(
            db_session, app_settings, _desired((IT, "smi"), revoke=((it, "smi"),))
        )

        assert [c.school_id for c in result.revoked_foreign] == [school_a]
        assert [c.school_id for c in result.granted_assignments] == [school_a]
        assert await _active(db_session) == {(it, "smi", school_a, "cockpit")}
        assert (await _report(db_session, app_settings))["rollen_fremd"] == []

    async def test_dry_run_reports_and_writes_nothing(
        self, db_session: AsyncSession, app_settings: Settings, school_a: int
    ) -> None:
        anna = synthetic_principal(ANNA)
        _grant(db_session, anna, "smi", school_a, "admin@example.ch")
        await db_session.commit()
        await _reconcile(db_session, app_settings, _desired())
        events = await _count(db_session, "role_revoked")

        result = await _reconcile(
            db_session, app_settings, _desired(revoke=((anna, "smi"),)), dry_run=True
        )

        assert [(c.principal, c.role) for c in result.revoked_foreign] == [(anna, "smi")]
        assert await _active(db_session) == {(anna, "smi", school_a, "admin@example.ch")}
        assert await _count(db_session, "role_revoked") == events
