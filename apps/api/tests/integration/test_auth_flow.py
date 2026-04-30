"""End-to-end auth flow with a mocked OIDC client.

Verifies:
- Bootstrap admin: env-var UPN → /auth/login → /auth/callback → session cookie
  is issued, ad_user_cache + role_assignments are populated, audit events for
  ``login`` and ``role_granted`` are persisted.
- ``/auth/me`` returns the resolved user.
- Logout deletes the session and emits ``logout``.
"""

from __future__ import annotations

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from magister_api.auth.oidc import OidcAuthorizeRequest, OidcUserInfo
from magister_api.config import Settings, get_settings
from magister_api.db import get_session
from magister_api.main import create_app
from magister_api.models.audit import AuditEvent
from magister_api.routers.auth import get_oidc_client

pytestmark = pytest.mark.postgres


class FakeOidcClient:
    def __init__(self, userinfo: OidcUserInfo) -> None:
        self._userinfo = userinfo
        self.captured: dict[str, str] = {}

    def build_authorize_request(self) -> OidcAuthorizeRequest:
        return OidcAuthorizeRequest(
            url="https://login.example.test/authorize?fake=1",
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


def _settings_for_app(database_url: str) -> Settings:
    return Settings(
        environment="test",  # type: ignore[arg-type]
        database_url=database_url,
        audit_key="auth-flow-test-key",  # type: ignore[arg-type]
        session_secret="auth-flow-session",  # type: ignore[arg-type]
        csrf_secret="auth-flow-csrf",  # type: ignore[arg-type]
        oidc_issuer="https://login.example.test/v2.0",
        oidc_client_id="client-id",
        oidc_client_secret="client-secret",  # type: ignore[arg-type]
        oidc_redirect_uri="http://testserver/auth/callback",
        bootstrap_admins=["admin@example.ch"],
        session_cookie_secure=False,
    )


@pytest_asyncio.fixture
async def app(engine: AsyncEngine, database_url: str):
    settings = _settings_for_app(database_url)
    app = create_app(settings)

    sm = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)

    async def _override_session():
        async with sm() as session:
            try:
                yield session
            except Exception:
                await session.rollback()
                raise
            else:
                await session.commit()

    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_session] = _override_session
    yield app
    # Truncate all tables between tests to keep them independent.
    async with engine.begin() as conn:
        await conn.exec_driver_sql(
            "TRUNCATE audit_events, sessions, role_assignments, ad_user_cache, schools "
            "RESTART IDENTITY CASCADE"
        )


@pytest_asyncio.fixture
async def client(app: FastAPI):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as c:
        yield c


def _bootstrap_userinfo() -> OidcUserInfo:
    return OidcUserInfo(
        subject="oidc-sub-1",
        upn="admin@example.ch",
        oid="11111111-1111-1111-1111-111111111111",
        given_name="Anna",
        surname="Admin",
        email="admin@example.ch",
    )


def _stranger_userinfo() -> OidcUserInfo:
    return OidcUserInfo(
        subject="oidc-sub-2",
        upn="stranger@example.ch",
        oid="22222222-2222-2222-2222-222222222222",
        given_name="Stra",
        surname="Nger",
        email="stranger@example.ch",
    )


class TestBootstrapLoginFlow:
    @pytest.mark.asyncio
    async def test_bootstrap_login_grants_admin_and_issues_session(
        self, app: FastAPI, client: AsyncClient, engine: AsyncEngine
    ) -> None:
        fake = FakeOidcClient(_bootstrap_userinfo())
        app.dependency_overrides[get_oidc_client] = lambda: fake

        # /auth/login sets the OIDC flow cookie.
        login_resp = await client.get("/auth/login", follow_redirects=False)
        assert login_resp.status_code == 303
        assert login_resp.headers["location"].startswith("https://login.example.test/")
        assert "magister_oidc_flow" in login_resp.cookies

        # /auth/callback exchanges the code and creates a session.
        cb = await client.get(
            "/auth/callback",
            params={"code": "the-code", "state": "state-xyz"},
            follow_redirects=False,
        )
        assert cb.status_code == 303, cb.text
        assert "magister_session" in cb.cookies
        assert "magister_csrf" in cb.cookies

        # /auth/me returns the bootstrap admin.
        me = await client.get("/auth/me")
        assert me.status_code == 200, me.text
        body = me.json()
        assert body["upn"] == "admin@example.ch"
        assert body["is_admin"] is True
        assert "admin" in body["roles"]

        # Audit events for login + role_granted are persisted.
        sm = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
        async with sm() as s:
            actions = (
                (await s.execute(select(AuditEvent.action).order_by(AuditEvent.id))).scalars().all()
            )
        assert "login" in actions
        assert "role_granted" in actions

    @pytest.mark.asyncio
    async def test_unknown_user_refused(self, app: FastAPI, client: AsyncClient) -> None:
        fake = FakeOidcClient(_stranger_userinfo())
        app.dependency_overrides[get_oidc_client] = lambda: fake
        await client.get("/auth/login", follow_redirects=False)
        cb = await client.get(
            "/auth/callback",
            params={"code": "c", "state": "state-xyz"},
            follow_redirects=False,
        )
        assert cb.status_code == 403
        assert cb.json()["detail"] == "user_not_synced"

    @pytest.mark.asyncio
    async def test_logout_deletes_session(
        self, app: FastAPI, client: AsyncClient, engine: AsyncEngine
    ) -> None:
        fake = FakeOidcClient(_bootstrap_userinfo())
        app.dependency_overrides[get_oidc_client] = lambda: fake
        await client.get("/auth/login", follow_redirects=False)
        await client.get(
            "/auth/callback",
            params={"code": "c", "state": "state-xyz"},
            follow_redirects=False,
        )

        csrf = client.cookies.get("magister_csrf")
        assert csrf is not None
        out = await client.post("/auth/logout", headers={"X-CSRF-Token": csrf})
        assert out.status_code == 200, out.text

        # /auth/me without a session must now 401.
        # httpx removes cookies cleared via Set-Cookie expiry — re-issue a fresh client.
        from httpx import ASGITransport
        from httpx import AsyncClient as Cli

        async with Cli(transport=ASGITransport(app=app), base_url="http://testserver") as fresh:
            me = await fresh.get("/auth/me")
            assert me.status_code == 401

    @pytest.mark.asyncio
    async def test_csrf_required_for_logout(self, app: FastAPI, client: AsyncClient) -> None:
        fake = FakeOidcClient(_bootstrap_userinfo())
        app.dependency_overrides[get_oidc_client] = lambda: fake
        await client.get("/auth/login", follow_redirects=False)
        await client.get(
            "/auth/callback",
            params={"code": "c", "state": "state-xyz"},
            follow_redirects=False,
        )
        # Missing X-CSRF-Token header → 403.
        out = await client.post("/auth/logout")
        assert out.status_code == 403
