"""Rollen aus dem Cockpit gegen eine echte Datenbank (ADR-0026).

Die Zusagen:

* Eine Liste ist **vollständig**: fehlende Zuweisungen kommen dazu, was das
  Cockpit früher vergab und nicht mehr nennt, wird zurückgenommen.
* ``schulleitung`` und ``smi`` gelten an **jeder** Einheit; eine neue Einheit
  ergänzt der nächste Abgleich.
* Von Hand oder per Bootstrap vergebene Zuweisungen fasst der Abgleich nie an.
* Ein zweiter Lauf ändert nichts und schreibt kein Audit.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from magister_api.audit.service import AuditService
from magister_api.auth.csrf import issue_csrf_token
from magister_api.config import Settings
from magister_api.models.audit import AuditEvent
from magister_api.models.auth import AdUserCache, LoginAccount, RoleAssignment, Session
from magister_api.models.base import utcnow
from magister_api.models.school import School
from magister_api.services.login_accounts import synthetic_principal
from magister_api.services.reconciler import RECONCILER_ACTOR, Reconciler, ReconcileResult
from magister_api.tenancy.desired_state import DesiredRoleAssignment, DesiredState

pytestmark = pytest.mark.postgres

LEITUNG = "kunde-a.leitung"
IT = "it@example.ch"


def _desired(*pairs: tuple[str, str]) -> DesiredState:
    return DesiredState(
        role_assignments=tuple(DesiredRoleAssignment(username=u, role=r) for u, r in pairs)
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


async def _rows(session: AsyncSession, guid: str) -> list[RoleAssignment]:
    stmt = select(RoleAssignment).where(RoleAssignment.ad_object_guid == guid)
    return list((await session.execute(stmt)).scalars().all())


async def _events(session: AsyncSession) -> int:
    stmt = select(func.count()).select_from(AuditEvent)
    return (await session.execute(stmt)).scalar_one()


async def _payloads(session: AsyncSession, settings: Settings, action: str) -> list[dict[str, Any]]:
    ids = (
        (
            await session.execute(
                select(AuditEvent.id).where(AuditEvent.action == action).order_by(AuditEvent.id)
            )
        )
        .scalars()
        .all()
    )
    audit = AuditService(session, settings)
    out: list[dict[str, Any]] = []
    for event_id in ids:
        record = await audit.read(event_id)
        assert record is not None
        out.append(dict(record.payload))
    return out


async def _school(session: AsyncSession, kuerzel: str) -> int:
    row = School(name=f"Einheit {kuerzel}", kuerzel=kuerzel, scope_short=kuerzel)
    session.add(row)
    await session.commit()
    return row.id


class TestGrant:
    async def test_a_missing_account_is_precreated_and_gets_the_role_at_every_unit(
        self,
        db_session: AsyncSession,
        app_settings: Settings,
        school_a: int,
        school_b: int,
    ) -> None:
        result = await _reconcile(db_session, app_settings, _desired((LEITUNG, "schulleitung")))

        guid = synthetic_principal(LEITUNG)
        assert result.created_login_accounts == [LEITUNG]
        assert {(c.principal_guid, c.role, c.school_id) for c in result.granted_assignments} == {
            (guid, "schulleitung", school_a),
            (guid, "schulleitung", school_b),
        }
        assert result.touched
        account = (
            await db_session.execute(select(LoginAccount).where(LoginAccount.username == LEITUNG))
        ).scalar_one()
        # vorab angelegt: bindet bei der ersten Anmeldung (ADR-0025 D2)
        assert account.subject is None
        assert account.principal_guid == guid
        assert await _active(db_session) == {
            (guid, "schulleitung", school_a, "cockpit"),
            (guid, "schulleitung", school_b, "cockpit"),
        }

        granted = await _payloads(db_session, app_settings, "role_granted")
        assert sorted(p["school_id"] for p in granted) == sorted([school_a, school_b])
        assert {p["via"] for p in granted} == {"cockpit"}
        assert {p["username"] for p in granted} == {LEITUNG}
        created = await _payloads(db_session, app_settings, "login_account_created")
        assert created == [{"username": LEITUNG, "principal_guid": guid, "via": "cockpit"}]
        actors = (await db_session.execute(select(AuditEvent.actor_upn).distinct())).scalars()
        assert set(actors) == {RECONCILER_ACTOR}

    async def test_admin_is_one_grant_without_a_unit(
        self, db_session: AsyncSession, app_settings: Settings, school_a: int
    ) -> None:
        await _reconcile(db_session, app_settings, _desired(("automato-admin", "admin")))

        guid = synthetic_principal("automato-admin")
        assert await _active(db_session) == {(guid, "admin", None, "cockpit")}

    async def test_an_existing_bound_account_keeps_its_principal(
        self, db_session: AsyncSession, app_settings: Settings, school_a: int
    ) -> None:
        db_session.add(
            LoginAccount(
                username="anna",
                principal_guid="00000000-0000-0000-0000-0000000000aa",
                issuer="https://sso.example.ch/realms/kunde-a",
                subject="sub-anna",
            )
        )
        await db_session.commit()

        result = await _reconcile(db_session, app_settings, _desired(("anna", "smi")))

        assert result.created_login_accounts == []
        assert await _active(db_session) == {
            ("00000000-0000-0000-0000-0000000000aa", "smi", school_a, "cockpit")
        }

    async def test_an_ad_person_gets_the_role_on_its_object_guid(
        self, db_session: AsyncSession, app_settings: Settings, school_a: int
    ) -> None:
        """Wie bei der Anmeldung: ``upn == username`` → die objectGUID (ADR-0025 D2)."""
        ad_guid = "11111111-2222-3333-4444-555555555555"
        db_session.add(
            AdUserCache(ad_object_guid=ad_guid, upn="It@Example.ch", kind="teacher", enabled=True)
        )
        await db_session.commit()

        await _reconcile(db_session, app_settings, _desired((IT, "smi")))

        assert await _active(db_session) == {(ad_guid, "smi", school_a, "cockpit")}
        account = (
            await db_session.execute(select(LoginAccount).where(LoginAccount.username == IT))
        ).scalar_one()
        assert account.principal_guid == ad_guid

    async def test_without_units_leitung_waits_for_the_first_unit(
        self, db_session: AsyncSession, app_settings: Settings
    ) -> None:
        result = await _reconcile(db_session, app_settings, _desired((LEITUNG, "schulleitung")))

        # Das Konto wird angelegt, Zuweisungen gibt es noch keine.
        assert result.created_login_accounts == [LEITUNG]
        assert await _active(db_session) == set()

        unit = await _school(db_session, "N")
        second = await _reconcile(db_session, app_settings, _desired((LEITUNG, "schulleitung")))

        assert [c.school_id for c in second.granted_assignments] == [unit]


class TestIdempotent:
    async def test_the_second_run_changes_nothing_and_writes_no_audit(
        self,
        db_session: AsyncSession,
        app_settings: Settings,
        school_a: int,
        school_b: int,
    ) -> None:
        desired = _desired((LEITUNG, "schulleitung"), (IT, "smi"), ("automato-admin", "admin"))
        first = await _reconcile(db_session, app_settings, desired)
        assert first.touched
        state, events = await _active(db_session), await _events(db_session)

        second = await _reconcile(db_session, app_settings, desired)

        assert not second.touched
        assert second.granted_assignments == []
        assert second.revoked_assignments == []
        assert second.created_login_accounts == []
        assert await _active(db_session) == state
        assert await _events(db_session) == events


class TestRevoke:
    async def test_what_the_cockpit_no_longer_lists_is_revoked(
        self,
        db_session: AsyncSession,
        app_settings: Settings,
        school_a: int,
        school_b: int,
    ) -> None:
        await _reconcile(db_session, app_settings, _desired((LEITUNG, "schulleitung"), (IT, "smi")))

        result = await _reconcile(db_session, app_settings, _desired((IT, "smi")))

        guid = synthetic_principal(LEITUNG)
        assert {(c.username, c.school_id) for c in result.revoked_assignments} == {
            (LEITUNG, school_a),
            (LEITUNG, school_b),
        }
        assert {r.revoked_at is not None for r in await _rows(db_session, guid)} == {True}
        revoked = await _payloads(db_session, app_settings, "role_revoked")
        assert {(p["role"], p["via"], p["username"]) for p in revoked} == {
            ("schulleitung", "cockpit", LEITUNG)
        }
        # Das Konto bleibt: Konten verwaltet der Abgleich nicht weg.
        assert (
            await db_session.execute(select(LoginAccount).where(LoginAccount.username == LEITUNG))
        ).scalar_one_or_none() is not None

    async def test_an_empty_list_revokes_everything_from_the_cockpit(
        self, db_session: AsyncSession, app_settings: Settings, school_a: int
    ) -> None:
        await _reconcile(db_session, app_settings, _desired(("automato-admin", "admin")))

        await _reconcile(db_session, app_settings, _desired())

        assert await _active(db_session) == set()

    async def test_no_statement_leaves_everything_as_it_is(
        self, db_session: AsyncSession, app_settings: Settings, school_a: int
    ) -> None:
        await _reconcile(db_session, app_settings, _desired((IT, "smi")))
        state, events = await _active(db_session), await _events(db_session)

        result = await _reconcile(db_session, app_settings, DesiredState(role_assignments=None))

        assert not result.touched
        assert await _active(db_session) == state
        assert await _events(db_session) == events

    async def test_a_role_given_back_by_the_cockpit_revives_its_row(
        self, db_session: AsyncSession, app_settings: Settings, school_a: int
    ) -> None:
        await _reconcile(db_session, app_settings, _desired((IT, "smi")))
        await _reconcile(db_session, app_settings, _desired())

        result = await _reconcile(db_session, app_settings, _desired((IT, "smi")))

        assert len(result.granted_assignments) == 1
        rows = await _rows(db_session, synthetic_principal(IT))
        assert len(rows) == 1
        assert rows[0].revoked_at is None
        assert rows[0].granted_by == "cockpit"


class TestOtherSourcesStay:
    async def test_hand_grants_are_neither_doubled_nor_revoked(
        self,
        db_session: AsyncSession,
        app_settings: Settings,
        school_a: int,
        school_b: int,
    ) -> None:
        guid = synthetic_principal(LEITUNG)
        db_session.add(
            RoleAssignment(
                ad_object_guid=guid,
                role="schulleitung",
                school_id=school_a,
                granted_by="admin@example.ch",
            )
        )
        await db_session.commit()

        result = await _reconcile(db_session, app_settings, _desired((LEITUNG, "schulleitung")))

        assert [c.school_id for c in result.granted_assignments] == [school_b]
        assert await _active(db_session) == {
            (guid, "schulleitung", school_a, "admin@example.ch"),
            (guid, "schulleitung", school_b, "cockpit"),
        }

        await _reconcile(db_session, app_settings, _desired())

        assert await _active(db_session) == {(guid, "schulleitung", school_a, "admin@example.ch")}

    async def test_a_bootstrap_admin_stays_admin(
        self, db_session: AsyncSession, app_settings: Settings
    ) -> None:
        guid = synthetic_principal("automato-admin")
        db_session.add(
            RoleAssignment(
                ad_object_guid=guid, role="admin", school_id=None, granted_by="bootstrap"
            )
        )
        await db_session.commit()

        listed = await _reconcile(db_session, app_settings, _desired(("automato-admin", "admin")))
        removed = await _reconcile(db_session, app_settings, _desired())

        assert listed.granted_assignments == []
        assert removed.revoked_assignments == []
        assert await _active(db_session) == {(guid, "admin", None, "bootstrap")}


class TestConflict:
    async def test_a_conflicting_entry_is_skipped_and_the_rest_runs(
        self, db_session: AsyncSession, app_settings: Settings, school_a: int
    ) -> None:
        """Ein anderes Konto hält schon die GUID (in Keycloak umbenannt, seither
        nicht angemeldet): ausgelassen und gemeldet, die übrigen Einträge laufen."""
        db_session.add(
            LoginAccount(
                username="anna.alt",
                principal_guid=synthetic_principal("anna"),
                issuer="https://sso.example.ch/realms/kunde-a",
                subject="sub-anna",
            )
        )
        await db_session.commit()

        result = await _reconcile(db_session, app_settings, _desired(("anna", "smi"), (IT, "smi")))

        assert result.skipped_assignments == {"anna": "account_principal_conflict"}
        # … und die Zustandsmeldung trägt es ins Cockpit, wo die Liste steht.
        assert result.problems == ["role_assignments anna: account_principal_conflict"]
        assert result.created_login_accounts == [IT]
        assert await _active(db_session) == {(synthetic_principal(IT), "smi", school_a, "cockpit")}
        # Kein Konto „anna" — und keine Rolle an der GUID des anderen Kontos.
        assert (
            await db_session.execute(select(LoginAccount).where(LoginAccount.username == "anna"))
        ).scalar_one_or_none() is None


class TestDryRun:
    async def test_dry_run_reports_and_writes_nothing(
        self, db_session: AsyncSession, app_settings: Settings, school_a: int
    ) -> None:
        await _reconcile(db_session, app_settings, _desired((IT, "smi")))
        state, events = await _active(db_session), await _events(db_session)

        result = await _reconcile(
            db_session, app_settings, _desired((LEITUNG, "schulleitung")), dry_run=True
        )

        assert result.created_login_accounts == [LEITUNG]
        assert [c.username for c in result.granted_assignments] == [LEITUNG]
        assert [c.username for c in result.revoked_assignments] == [IT]
        assert await _active(db_session) == state
        assert await _events(db_session) == events
        assert (
            await db_session.execute(select(LoginAccount).where(LoginAccount.username == LEITUNG))
        ).scalar_one_or_none() is None


class TestNextRequest:
    async def test_a_revoked_role_is_gone_with_the_next_request(
        self, app: FastAPI, db_session: AsyncSession, app_settings: Settings
    ) -> None:
        """Rechte werden je Anfrage gelesen, nicht in der Sitzung gehalten."""
        await _reconcile(db_session, app_settings, _desired(("kunde-a.admin", "admin")))
        guid = synthetic_principal("kunde-a.admin")
        now = utcnow()
        db_session.add(
            Session(
                id="sid-kunde-a-admin",
                ad_object_guid=guid,
                oidc_subject="sub-kunde-a-admin",
                auth_kind="oidc",
                expires_at=now + timedelta(hours=1),
                last_seen_at=now,
                created_at=now,
            )
        )
        await db_session.commit()
        csrf = issue_csrf_token("sid-kunde-a-admin", app_settings)
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://testserver",
            cookies={"magister_session": "sid-kunde-a-admin", "magister_csrf": csrf},
            headers={"X-CSRF-Token": csrf},
        ) as client:
            before = await client.get("/admin/roles")
            assert before.status_code == 200
            assert [a["from_cockpit"] for a in before.json()] == [True]

            await _reconcile(db_session, app_settings, _desired())

            after = await client.get("/admin/roles")
            assert after.status_code == 403


class TestUnits:
    async def test_a_unit_with_cockpit_grants_can_be_deleted(
        self,
        as_admin: AsyncClient,
        db_session: AsyncSession,
        app_settings: Settings,
        school_a: int,
    ) -> None:
        """Die Rolle gilt für den ganzen Kunden; an einer gelöschten Einheit hat
        sie nichts zu suchen und hält das Löschen nicht auf."""
        unit = await _school(db_session, "WEG")
        await _reconcile(db_session, app_settings, _desired((LEITUNG, "schulleitung"), (IT, "smi")))
        await _reconcile(db_session, app_settings, _desired((LEITUNG, "schulleitung")))

        deleted = await as_admin.delete(f"/schools/{unit}")

        assert deleted.status_code == 204, deleted.text
        guid = synthetic_principal(LEITUNG)
        cockpit = {a for a in await _active(db_session) if a[3] == "cockpit"}
        assert cockpit == {(guid, "schulleitung", school_a, "cockpit")}
        revoked = [
            p
            for p in await _payloads(db_session, app_settings, "role_revoked")
            if p["via"] == "school_deleted"
        ]
        assert revoked == [{"role": "schulleitung", "school_id": unit, "via": "school_deleted"}]
        # Der nächste Abgleich legt nichts wieder an.
        again = await _reconcile(db_session, app_settings, _desired((LEITUNG, "schulleitung")))
        assert not again.touched

    async def test_a_hand_grant_still_blocks_deleting_a_unit(
        self, as_admin: AsyncClient, db_session: AsyncSession
    ) -> None:
        unit = await _school(db_session, "HAND")
        db_session.add(
            RoleAssignment(
                ad_object_guid=synthetic_principal("anna"),
                role="smi",
                school_id=unit,
                granted_by="admin@example.ch",
            )
        )
        await db_session.commit()

        resp = await as_admin.delete(f"/schools/{unit}")

        assert resp.status_code == 409
        assert resp.json()["detail"] == "school_in_use"


class TestAdminUi:
    async def test_the_admin_ui_can_grant_a_revoked_role_again(
        self, as_admin: AsyncClient, school_a: int, db_session: AsyncSession
    ) -> None:
        """Vergeben, entziehen, wieder vergeben — die Zeile lebt wieder auf.

        Die Eindeutigkeit (Person, Rolle, Einheit) gilt auch für
        zurückgenommene Zeilen; ein zweites INSERT scheiterte daran.
        """
        created = await as_admin.post("/admin/login-accounts", json={"username": LEITUNG})
        guid = created.json()["principal_guid"]
        body = {"assignments": [{"role": "schulleitung", "school_id": school_a}]}

        assert (await as_admin.put(f"/admin/users/{guid}/roles", json=body)).status_code == 200
        assert (
            await as_admin.put(f"/admin/users/{guid}/roles", json={"assignments": []})
        ).status_code == 200
        again = await as_admin.put(f"/admin/users/{guid}/roles", json=body)

        assert again.status_code == 200, again.text
        rows = await _rows(db_session, guid)
        assert len(rows) == 1
        assert rows[0].revoked_at is None
        assert rows[0].granted_by == "admin@example.ch"

    async def test_cockpit_grants_are_marked_and_hand_grants_not(
        self,
        as_admin: AsyncClient,
        db_session: AsyncSession,
        app_settings: Settings,
        school_a: int,
    ) -> None:
        await _reconcile(db_session, app_settings, _desired((IT, "smi")))

        listed = (await as_admin.get("/admin/roles")).json()

        marks = {(a["upn"], a["role"]): a["from_cockpit"] for a in listed}
        assert marks == {(IT, "smi"): True, ("admin@example.ch", "admin"): False}

    async def test_a_keycloak_user_named_cockpit_does_not_grant_as_the_cockpit(
        self, app: FastAPI, db_session: AsyncSession, app_settings: Settings, school_a: int
    ) -> None:
        """Sonst nähme der nächste Abgleich die Vergabe als „nicht mehr gewollt" zurück."""
        guid = synthetic_principal("cockpit")
        now = utcnow()
        db_session.add(LoginAccount(username="cockpit", principal_guid=guid))
        db_session.add(
            RoleAssignment(ad_object_guid=guid, role="admin", school_id=None, granted_by="test")
        )
        db_session.add(
            Session(
                id="sid-cockpit",
                ad_object_guid=guid,
                oidc_subject="sub-cockpit",
                auth_kind="oidc",
                expires_at=now + timedelta(hours=1),
                last_seen_at=now,
                created_at=now,
            )
        )
        await db_session.commit()
        csrf = issue_csrf_token("sid-cockpit", app_settings)
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://testserver",
            cookies={"magister_session": "sid-cockpit", "magister_csrf": csrf},
            headers={"X-CSRF-Token": csrf},
        ) as client:
            target = synthetic_principal("anna")
            db_session.add(LoginAccount(username="anna", principal_guid=target))
            await db_session.commit()
            resp = await client.put(
                f"/admin/users/{target}/roles",
                json={"assignments": [{"role": "smi", "school_id": school_a}]},
            )
            assert resp.status_code == 200, resp.text
            assert resp.json()[0]["granted_by"] == "konto:cockpit"
            assert resp.json()[0]["from_cockpit"] is False
