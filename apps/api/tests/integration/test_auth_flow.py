"""End-to-end auth flow with a mocked OIDC client (ADR-0025: Anmeldung über Keycloak).

Verifies:
- Bootstrap admin by Keycloak user name — with and without ``@`` — gets the
  admin role, without an ``oid`` and without a row in ``ad_user_cache``.
- Every other realm user gets a login account on the first sign-in; without
  roles it sees nothing.
- A login account takes over the GUID of the AD user with the same UPN, so a
  teacher keeps classes and roles.
- A pre-created account binds the subject; the same user name with another
  subject is refused and audited.
- Logout deletes the session and names the realm's end-session address.
"""

from __future__ import annotations

from datetime import timedelta
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from magister_api.auth.oidc import OidcAuthorizeRequest, OidcUserInfo
from magister_api.models.audit import AuditEvent
from magister_api.models.auth import AdUserCache, LoginAccount, RoleAssignment, Session
from magister_api.models.base import utcnow
from magister_api.models.class_teacher_role import ClassTeacherRole
from magister_api.models.school_class import SchoolClass
from magister_api.routers.auth import get_oidc_client
from magister_api.services.login_accounts import synthetic_principal

pytestmark = pytest.mark.postgres

ISSUER = "https://sso.example.ch/realms/kunde-a"
END_SESSION = f"{ISSUER}/protocol/openid-connect/logout"


class FakeOidcClient:
    def __init__(self, userinfo: OidcUserInfo, *, end_session: str | None = END_SESSION) -> None:
        self._userinfo = userinfo
        self._end_session = end_session
        self.captured: dict[str, str] = {}

    async def build_authorize_request(self) -> OidcAuthorizeRequest:
        return OidcAuthorizeRequest(
            url="https://sso.example.ch/realms/kunde-a/protocol/openid-connect/auth?fake=1",
            state="state-xyz",
            nonce="nonce-xyz",
            code_verifier="verifier-xyz",
        )

    async def exchange_code(
        self, *, code: str, state: str, expected_state: str, code_verifier: str, nonce: str
    ) -> OidcUserInfo:
        self.captured = {
            "code": code,
            "state": state,
            "expected_state": expected_state,
            "code_verifier": code_verifier,
            "nonce": nonce,
        }
        if state != expected_state:
            raise ValueError("oidc_state_mismatch")
        return self._userinfo

    async def end_session_url(self) -> str | None:
        if self._end_session is None:
            return None
        return (
            f"{self._end_session}?client_id=magister"
            "&post_logout_redirect_uri=https%3A%2F%2Ftestserver%2Flogin"
        )


def _userinfo(
    username: str,
    *,
    subject: str | None = None,
    display_name: str | None = None,
) -> OidcUserInfo:
    return OidcUserInfo(
        issuer=ISSUER,
        subject=subject or f"sub-{username}",
        username=username,
        display_name=display_name,
        given_name=None,
        surname=None,
        email=None,
    )


async def _sign_in(app: FastAPI, client: AsyncClient, userinfo: OidcUserInfo) -> str:
    """Run login + callback; return the ``location`` of the callback answer."""
    app.dependency_overrides[get_oidc_client] = lambda: FakeOidcClient(userinfo)
    login = await client.get("/auth/login", follow_redirects=False)
    assert login.status_code == 303
    cb = await client.get(
        "/auth/callback",
        params={"code": "the-code", "state": "state-xyz"},
        follow_redirects=False,
    )
    assert cb.status_code == 303, cb.text
    return cb.headers["location"]


def _sm(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False, autoflush=False)


async def _actions(engine: AsyncEngine) -> list[str]:
    async with _sm(engine)() as s:
        return list(
            (await s.execute(select(AuditEvent.action).order_by(AuditEvent.id))).scalars().all()
        )


class TestBootstrapLoginFlow:
    @pytest.mark.asyncio
    async def test_bootstrap_login_grants_admin_and_issues_session(
        self, app: FastAPI, client: AsyncClient, engine: AsyncEngine
    ) -> None:
        fake = FakeOidcClient(_userinfo("admin@example.ch", display_name="Anna Admin"))
        app.dependency_overrides[get_oidc_client] = lambda: fake

        # /auth/login sets the OIDC flow cookie.
        login_resp = await client.get("/auth/login", follow_redirects=False)
        assert login_resp.status_code == 303
        assert login_resp.headers["location"].startswith("https://sso.example.ch/")
        assert "magister_oidc_flow" in login_resp.cookies

        # /auth/callback exchanges the code and creates a session.
        cb = await client.get(
            "/auth/callback",
            params={"code": "the-code", "state": "state-xyz"},
            follow_redirects=False,
        )
        assert cb.status_code == 303, cb.text
        assert cb.headers["location"] == "/"
        assert "magister_session" in cb.cookies
        assert "magister_csrf" in cb.cookies

        # /auth/me returns the bootstrap admin.
        me = await client.get("/auth/me")
        assert me.status_code == 200, me.text
        body = me.json()
        assert body["upn"] == "admin@example.ch"
        assert body["display_name"] == "Anna Admin"
        assert body["is_admin"] is True
        assert body["has_permissions"] is True
        assert "admin" in body["roles"]

        actions = await _actions(engine)
        assert "login_account_created" in actions
        assert "login" in actions
        assert "role_granted" in actions

    @pytest.mark.asyncio
    async def test_bootstrap_by_user_name_without_at_and_without_ad_row(
        self, app: FastAPI, client: AsyncClient, engine: AsyncEngine
    ) -> None:
        """`automato-admin` steht nur in Keycloak — kein oid, keine AD-Zeile."""
        assert await _sign_in(app, client, _userinfo("automato-admin")) == "/"

        me = (await client.get("/auth/me")).json()
        assert me["upn"] == "automato-admin"
        assert me["is_admin"] is True
        guid = synthetic_principal("automato-admin")
        assert me["ad_object_guid"] == guid
        assert me["kind"] is None

        async with _sm(engine)() as s:
            assert await s.get(AdUserCache, guid) is None
            stmt = select(RoleAssignment).where(RoleAssignment.ad_object_guid == guid)
            roles = (await s.execute(stmt)).scalars().all()
        assert [(r.role, r.school_id, r.granted_by) for r in roles] == [
            ("admin", None, "bootstrap")
        ]

        # Das Konto darf, was ein Admin darf.
        assert (await client.get("/admin/roles")).status_code == 200

    @pytest.mark.asyncio
    async def test_bootstrap_grant_comes_back_after_revocation(
        self, app: FastAPI, client: AsyncClient, engine: AsyncEngine
    ) -> None:
        await _sign_in(app, client, _userinfo("automato-admin"))
        guid = synthetic_principal("automato-admin")
        async with _sm(engine)() as s:
            stmt = select(RoleAssignment).where(RoleAssignment.ad_object_guid == guid)
            for r in (await s.execute(stmt)).scalars().all():
                await s.delete(r)
            await s.commit()

        await _sign_in(app, client, _userinfo("automato-admin"))
        me = (await client.get("/auth/me")).json()
        assert me["is_admin"] is True


class TestLoginAccounts:
    @pytest.mark.asyncio
    async def test_first_login_without_roles_signs_in_but_sees_nothing(
        self, app: FastAPI, client: AsyncClient, engine: AsyncEngine
    ) -> None:
        # Vorher: `user_not_synced`. Jetzt kommt jeder Benutzer des Realms
        # hinein — und sieht nichts, bis ihm jemand Rechte gibt.
        assert await _sign_in(app, client, _userinfo("neu.person")) == "/"

        me = (await client.get("/auth/me")).json()
        assert me["upn"] == "neu.person"
        assert me["is_admin"] is False
        assert me["roles"] == []
        assert me["has_permissions"] is False

        assert (await client.get("/users")).status_code == 403
        assert (await client.get("/classes")).status_code == 403
        assert (await client.get("/admin/roles")).status_code == 403
        assert (await client.get("/admin/login-accounts")).status_code == 403

        async with _sm(engine)() as s:
            stmt = select(LoginAccount).where(LoginAccount.username == "neu.person")
            account = (await s.execute(stmt)).scalar_one()
        assert account.issuer == ISSUER
        assert account.subject == "sub-neu.person"
        assert account.principal_guid == synthetic_principal("neu.person")
        assert account.last_login_at is not None

    @pytest.mark.asyncio
    async def test_first_login_takes_the_guid_of_the_ad_user_with_the_same_upn(
        self, app: FastAPI, client: AsyncClient, engine: AsyncEngine, school_a: int
    ) -> None:
        guid = "abcdef01-2345-6789-abcd-ef0123456789"
        async with _sm(engine)() as s:
            s.add(
                AdUserCache(
                    ad_object_guid=guid,
                    school_id=school_a,
                    upn="lehrer.a@example.ch",
                    display_name="Lehrer A",
                    kind="teacher",
                    enabled=True,
                )
            )
            s.add(
                RoleAssignment(
                    ad_object_guid=guid, role="schulleitung", school_id=school_a, granted_by="t"
                )
            )
            await s.commit()

        assert await _sign_in(app, client, _userinfo("lehrer.a@example.ch")) == "/"

        me = (await client.get("/auth/me")).json()
        assert me["ad_object_guid"] == guid
        assert me["kind"] == "teacher"
        assert me["display_name"] == "Lehrer A"
        assert me["roles"] == ["schulleitung"]
        assert me["school_scope"] == [school_a]
        assert me["has_permissions"] is True

    @pytest.mark.asyncio
    async def test_a_class_teacher_without_role_assignments_has_permissions(
        self, app: FastAPI, client: AsyncClient, engine: AsyncEngine, school_a: int
    ) -> None:
        """Klassenlehrer ist eine abgeleitete Rolle — sie steht nicht in `roles`."""
        guid = "abcdef01-2345-6789-abcd-ef0123456781"
        async with _sm(engine)() as s:
            s.add(
                AdUserCache(
                    ad_object_guid=guid,
                    school_id=school_a,
                    upn="kl@example.ch",
                    kind="teacher",
                    enabled=True,
                )
            )
            klasse = SchoolClass(school_id=school_a, name="3a", jahrgangsstufe=3)
            s.add(klasse)
            await s.flush()
            s.add(
                ClassTeacherRole(
                    class_id=klasse.id,
                    ad_object_guid=guid,
                    role="haupt",
                    valid_from=utcnow() - timedelta(days=1),
                )
            )
            await s.commit()

        await _sign_in(app, client, _userinfo("kl@example.ch"))
        me = (await client.get("/auth/me")).json()
        assert me["roles"] == []
        assert me["has_permissions"] is True

    @pytest.mark.asyncio
    async def test_a_disabled_ad_user_is_refused(
        self, app: FastAPI, client: AsyncClient, engine: AsyncEngine, school_a: int
    ) -> None:
        async with _sm(engine)() as s:
            s.add(
                AdUserCache(
                    ad_object_guid="abcdef01-2345-6789-abcd-ef0123456780",
                    school_id=school_a,
                    upn="weg@example.ch",
                    kind="teacher",
                    enabled=False,
                )
            )
            await s.commit()
        location = await _sign_in(app, client, _userinfo("weg@example.ch"))
        assert location == "/login?error=user_disabled"

    @pytest.mark.asyncio
    async def test_a_precreated_account_binds_the_subject(
        self, app: FastAPI, client: AsyncClient, engine: AsyncEngine
    ) -> None:
        guid = synthetic_principal("vorab")
        async with _sm(engine)() as s:
            s.add(LoginAccount(username="vorab", principal_guid=guid, display_name="Vorab"))
            s.add(RoleAssignment(ad_object_guid=guid, role="admin", granted_by="t"))
            await s.commit()

        assert await _sign_in(app, client, _userinfo("vorab", subject="kc-sub-1")) == "/"
        me = (await client.get("/auth/me")).json()
        assert me["is_admin"] is True
        assert me["ad_object_guid"] == guid

        async with _sm(engine)() as s:
            stmt = select(LoginAccount).where(LoginAccount.username == "vorab")
            account = (await s.execute(stmt)).scalar_one()
        assert (account.issuer, account.subject) == (ISSUER, "kc-sub-1")
        actions = await _actions(engine)
        assert "login_account_bound" in actions
        assert "login_account_created" not in actions

    @pytest.mark.asyncio
    async def test_same_user_name_with_another_subject_is_refused(
        self, app: FastAPI, client: AsyncClient, engine: AsyncEngine
    ) -> None:
        # Erste Anmeldung bindet das Konto an kc-sub-1 …
        assert await _sign_in(app, client, _userinfo("person", subject="kc-sub-1")) == "/"

        # … ein neu angelegter Keycloak-Benutzer mit demselben Namen übernimmt
        # das Konto nicht.
        app.dependency_overrides[get_oidc_client] = lambda: FakeOidcClient(
            _userinfo("person", subject="kc-sub-2")
        )
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://testserver"
        ) as other:
            await other.get("/auth/login", follow_redirects=False)
            cb = await other.get(
                "/auth/callback",
                params={"code": "c", "state": "state-xyz"},
                follow_redirects=False,
            )
        assert cb.status_code == 303
        assert cb.headers["location"] == "/login?error=account_bound_to_other_subject"
        assert "magister_session" not in cb.cookies

        async with _sm(engine)() as s:
            stmt = select(LoginAccount).where(LoginAccount.username == "person")
            account = (await s.execute(stmt)).scalar_one()
            refused_stmt = select(AuditEvent).where(AuditEvent.action == "login_refused")
            refused = (await s.execute(refused_stmt)).scalar_one()
        assert account.subject == "kc-sub-1"
        assert refused.actor_upn == "person"

    @pytest.mark.asyncio
    async def test_a_disabled_account_is_refused(
        self, app: FastAPI, client: AsyncClient, engine: AsyncEngine
    ) -> None:
        async with _sm(engine)() as s:
            s.add(
                LoginAccount(
                    username="gesperrt",
                    principal_guid=synthetic_principal("gesperrt"),
                    enabled=False,
                )
            )
            await s.commit()
        location = await _sign_in(app, client, _userinfo("gesperrt"))
        assert location == "/login?error=account_disabled"
        async with _sm(engine)() as s:
            stmt = select(LoginAccount).where(LoginAccount.username == "gesperrt")
            account = (await s.execute(stmt)).scalar_one()
        # Ein gesperrtes Konto wird nicht gebunden.
        assert account.subject is None

    @pytest.mark.asyncio
    async def test_a_renamed_keycloak_user_keeps_its_account(
        self, app: FastAPI, client: AsyncClient
    ) -> None:
        await _sign_in(app, client, _userinfo("alt.name", subject="kc-sub-9"))
        await _sign_in(app, client, _userinfo("neu.name", subject="kc-sub-9"))
        me = (await client.get("/auth/me")).json()
        assert me["upn"] == "neu.name"
        # Die GUID bleibt die beim Anlegen vergebene.
        assert me["ad_object_guid"] == synthetic_principal("alt.name")


class TestCallbackErrors:
    @pytest.mark.asyncio
    async def test_a_provider_error_goes_back_to_the_login_page(
        self, app: FastAPI, client: AsyncClient
    ) -> None:
        fake = FakeOidcClient(_userinfo("automato-admin"))
        app.dependency_overrides[get_oidc_client] = lambda: fake
        cb = await client.get(
            "/auth/callback",
            params={"error": "access_denied", "error_description": "<b>fremder Text</b>"},
            follow_redirects=False,
        )
        assert cb.status_code == 303
        assert cb.headers["location"] == "/login?error=oidc_error&idp=access_denied"

    @pytest.mark.asyncio
    async def test_a_stale_or_foreign_callback_goes_back_to_the_login_page(
        self, app: FastAPI, client: AsyncClient
    ) -> None:
        fake = FakeOidcClient(_userinfo("automato-admin"))
        app.dependency_overrides[get_oidc_client] = lambda: fake
        cb = await client.get(
            "/auth/callback", params={"code": "c", "state": "s"}, follow_redirects=False
        )
        assert cb.status_code == 303
        assert cb.headers["location"] == "/login?error=oidc_callback_invalid"


class TestLogout:
    @pytest.mark.asyncio
    async def test_logout_deletes_session_and_names_the_realm_logout(
        self, app: FastAPI, client: AsyncClient, engine: AsyncEngine
    ) -> None:
        await _sign_in(app, client, _userinfo("automato-admin"))

        csrf = client.cookies.get("magister_csrf")
        assert csrf is not None
        out = await client.post("/auth/logout", headers={"X-CSRF-Token": csrf})
        assert out.status_code == 200, out.text
        body = out.json()
        assert body["ok"] is True
        target = urlparse(body["redirect"])
        assert f"{target.scheme}://{target.netloc}{target.path}" == END_SESSION
        params = parse_qs(target.query)
        assert params["client_id"] == ["magister"]
        assert params["post_logout_redirect_uri"] == ["https://testserver/login"]
        assert "id_token_hint" not in params

        async with _sm(engine)() as s:
            assert (await s.execute(select(Session))).scalars().all() == []

        # /auth/me without a session must now 401.
        # httpx removes cookies cleared via Set-Cookie expiry — re-issue a fresh client.
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://testserver"
        ) as fresh:
            me = await fresh.get("/auth/me")
            assert me.status_code == 401
        assert "logout" in await _actions(engine)

    @pytest.mark.asyncio
    async def test_logout_without_end_session_endpoint_stays_local(
        self, app: FastAPI, client: AsyncClient
    ) -> None:
        await _sign_in(app, client, _userinfo("automato-admin"))
        app.dependency_overrides[get_oidc_client] = lambda: FakeOidcClient(
            _userinfo("automato-admin"), end_session=None
        )
        out = await client.post("/auth/logout")
        assert out.status_code == 200
        assert out.json() == {"ok": True}

    @pytest.mark.asyncio
    async def test_logout_is_csrf_exempt(self, app: FastAPI, client: AsyncClient) -> None:
        await _sign_in(app, client, _userinfo("automato-admin"))
        # Logout is deliberately CSRF-exempt (it still requires a valid session
        # cookie; a stale csrf cookie must not be able to block sign-out).
        out = await client.post("/auth/logout")
        assert out.status_code == 200
        assert out.json()["ok"] is True
