"""Anmeldekonten in der Admin-Oberfläche (ADR-0025).

Vorab anlegen, Rollen an ein Konto ohne AD-Zeile vergeben, sperren (beendet
die Sitzungen), Bindung lösen, löschen — und die Grenzen: Benutzername-Regel,
Doppel, Bootstrap-Admins, Nicht-Admins.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from magister_api.models.audit import AuditEvent
from magister_api.models.auth import AdUserCache, LoginAccount, RoleAssignment, Session
from magister_api.models.base import utcnow
from magister_api.services.login_accounts import synthetic_principal

pytestmark = pytest.mark.postgres


def _sm(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False, autoflush=False)


async def _bound_account_with_session(engine: AsyncEngine, username: str) -> LoginAccount:
    guid = synthetic_principal(username)
    now = utcnow()
    async with _sm(engine)() as s:
        account = LoginAccount(
            username=username,
            principal_guid=guid,
            issuer="https://sso.example.ch/realms/kunde-a",
            subject=f"sub-{username}",
        )
        s.add(account)
        s.add(
            Session(
                id=f"sid-{username}"[:64],
                ad_object_guid=guid,
                oidc_subject=f"sub-{username}",
                auth_kind="oidc",
                expires_at=now + timedelta(hours=1),
                last_seen_at=now,
                created_at=now,
            )
        )
        await s.commit()
        return account


async def _sessions(engine: AsyncEngine, guid: str) -> list[Session]:
    async with _sm(engine)() as s:
        stmt = select(Session).where(Session.ad_object_guid == guid)
        return list((await s.execute(stmt)).scalars().all())


class TestPrecreateAndAssign:
    @pytest.mark.asyncio
    async def test_precreate_then_grant_a_role_without_an_ad_row(
        self, as_admin: AsyncClient, engine: AsyncEngine, school_a: int
    ) -> None:
        created = await as_admin.post(
            "/admin/login-accounts", json={"username": "Neue.Person", "display_name": "Neue P."}
        )
        assert created.status_code == 201, created.text
        body = created.json()
        assert body["username"] == "neue.person"
        assert body["principal_guid"] == synthetic_principal("neue.person")
        assert body["bound"] is False
        assert body["ad_linked"] is False

        guid = body["principal_guid"]
        put = await as_admin.put(
            f"/admin/users/{guid}/roles",
            json={"assignments": [{"role": "schulleitung", "school_id": school_a}]},
        )
        assert put.status_code == 200, put.text
        assert put.json()[0]["upn"] == "neue.person"

        listed = (await as_admin.get("/admin/roles")).json()
        holder = next(r for r in listed if r["ad_object_guid"] == guid)
        assert holder["upn"] == "neue.person"
        assert holder["display_name"] == "Neue P."

        async with _sm(engine)() as s:
            actions = (
                (await s.execute(select(AuditEvent.action).order_by(AuditEvent.id))).scalars().all()
            )
        assert "login_account_created" in actions
        assert "role_granted" in actions

    @pytest.mark.asyncio
    async def test_precreate_links_the_ad_user_with_the_same_upn(
        self, as_admin: AsyncClient, engine: AsyncEngine, school_a: int
    ) -> None:
        guid = "abcdef01-2345-6789-abcd-ef01234567aa"
        async with _sm(engine)() as s:
            s.add(
                AdUserCache(
                    ad_object_guid=guid,
                    school_id=school_a,
                    upn="lehrer.b@example.ch",
                    kind="teacher",
                    enabled=True,
                )
            )
            await s.commit()
        created = await as_admin.post(
            "/admin/login-accounts", json={"username": "lehrer.b@example.ch"}
        )
        assert created.status_code == 201
        assert created.json()["principal_guid"] == guid
        assert created.json()["ad_linked"] is True

    @pytest.mark.asyncio
    async def test_duplicates_and_bad_names_are_refused(self, as_admin: AsyncClient) -> None:
        assert (
            await as_admin.post("/admin/login-accounts", json={"username": "doppelt"})
        ).status_code == 201
        again = await as_admin.post("/admin/login-accounts", json={"username": "DOPPELT"})
        assert again.status_code == 409
        assert again.json()["detail"] == "login_account_exists"
        for bad in ("mit leer", "", "x" * 256, "tab\there"):
            resp = await as_admin.post("/admin/login-accounts", json={"username": bad})
            assert resp.status_code == 422, bad

    @pytest.mark.asyncio
    async def test_grant_to_an_unknown_guid_is_404(self, as_admin: AsyncClient) -> None:
        resp = await as_admin.put(
            f"/admin/users/{synthetic_principal('niemand')}/roles", json={"assignments": []}
        )
        assert resp.status_code == 404
        assert resp.json()["detail"] == "user_not_found"


class TestManage:
    @pytest.mark.asyncio
    async def test_disable_ends_sessions_and_enable_restores(
        self, as_admin: AsyncClient, engine: AsyncEngine
    ) -> None:
        account = await _bound_account_with_session(engine, "zu.sperren")
        assert len(await _sessions(engine, account.principal_guid)) == 1

        off = await as_admin.patch(f"/admin/login-accounts/{account.id}", json={"enabled": False})
        assert off.status_code == 200, off.text
        assert off.json()["enabled"] is False
        assert await _sessions(engine, account.principal_guid) == []

        on = await as_admin.patch(f"/admin/login-accounts/{account.id}", json={"enabled": True})
        assert on.json()["enabled"] is True

    @pytest.mark.asyncio
    async def test_unbind_clears_the_subject(
        self, as_admin: AsyncClient, engine: AsyncEngine
    ) -> None:
        account = await _bound_account_with_session(engine, "neu.binden")
        resp = await as_admin.post(f"/admin/login-accounts/{account.id}/unbind")
        assert resp.status_code == 200
        assert resp.json()["bound"] is False
        assert await _sessions(engine, account.principal_guid) == []
        async with _sm(engine)() as s:
            row = await s.get(LoginAccount, account.id)
        assert row is not None
        assert (row.issuer, row.subject) == (None, None)

    @pytest.mark.asyncio
    async def test_delete_keeps_the_roles(self, as_admin: AsyncClient, engine: AsyncEngine) -> None:
        account = await _bound_account_with_session(engine, "weg.damit")
        async with _sm(engine)() as s:
            s.add(
                RoleAssignment(ad_object_guid=account.principal_guid, role="admin", granted_by="t")
            )
            await s.commit()
        resp = await as_admin.delete(f"/admin/login-accounts/{account.id}")
        assert resp.status_code == 204
        async with _sm(engine)() as s:
            assert await s.get(LoginAccount, account.id) is None
            stmt = select(RoleAssignment).where(
                RoleAssignment.ad_object_guid == account.principal_guid
            )
            assert len((await s.execute(stmt)).scalars().all()) == 1
        assert await _sessions(engine, account.principal_guid) == []

    @pytest.mark.asyncio
    async def test_bootstrap_admins_cannot_be_locked_out(
        self, as_admin: AsyncClient, engine: AsyncEngine
    ) -> None:
        account = await _bound_account_with_session(engine, "automato-admin")
        listed = (await as_admin.get("/admin/login-accounts", params={"search": "automato"})).json()
        assert [a["username"] for a in listed] == ["automato-admin"]
        assert listed[0]["bootstrap_admin"] is True

        off = await as_admin.patch(f"/admin/login-accounts/{account.id}", json={"enabled": False})
        assert off.status_code == 409
        assert off.json()["detail"] == "login_account_is_bootstrap_admin"
        gone = await as_admin.delete(f"/admin/login-accounts/{account.id}")
        assert gone.status_code == 409

    @pytest.mark.asyncio
    async def test_unknown_account_is_404(self, as_admin: AsyncClient) -> None:
        resp = await as_admin.patch("/admin/login-accounts/999", json={"enabled": False})
        assert resp.status_code == 404
        assert resp.json()["detail"] == "login_account_not_found"

    @pytest.mark.asyncio
    async def test_only_admins(self, as_schulleitung_a: AsyncClient) -> None:
        assert (await as_schulleitung_a.get("/admin/login-accounts")).status_code == 403
        resp = await as_schulleitung_a.post("/admin/login-accounts", json={"username": "x"})
        assert resp.status_code == 403
