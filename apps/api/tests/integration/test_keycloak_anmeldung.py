"""Die Anmeldung gegen einen echten Keycloak (ADR-0025, Nachtrag 2026-11-16).

Die übrigen Tests der Anmeldung ersetzen den Anbieter (`FakeOidcClient`) oder
seine Antworten (MockTransport). Was sie nicht zeigen: dass Magister mit dem
Client, wie das Cockpit ihn im Realm anlegt, wirklich hineinkommt — Discovery,
Anmeldeformular, Code-Tausch mit PKCE und Secret, Signatur gegen die JWKS,
`iss`/`aud`/`nonce`, Abmelden mit `post_logout_redirect_uri` — und dass die
Selbstprüfung einen echten Realm als in Ordnung erkennt und einen falschen
Issuer nicht.

Läuft nur mit ``MAGISTER_TEST_KEYCLOAK_URL`` (etwa ``http://127.0.0.1:8180``,
Keycloak ``start-dev``) und ``MAGISTER_TEST_KEYCLOAK_ADMIN_PASSWORD`` (Admin
des Realms ``master``, Benutzer aus ``MAGISTER_TEST_KEYCLOAK_ADMIN``, Vorgabe
``admin``), sonst übersprungen. ``127.0.0.1`` statt ``localhost``: die
Cookie-Ablage von Python legt Cookies für ``localhost`` unter
``localhost.local`` ab und schickt sie nicht zurück. Jeder Test legt einen
eigenen Realm an und löscht ihn danach.
"""

from __future__ import annotations

import ast
import html
import os
import re
import secrets
from collections.abc import AsyncIterator
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any
from urllib.parse import parse_qs, urljoin, urlsplit

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from magister_api.auth.oidc_check import check_oidc
from magister_api.config import Settings, get_settings
from magister_api.models.auth import LoginAccount, Session
from tests.konsole import konsole_datei

pytestmark = [pytest.mark.postgres, pytest.mark.keycloak]

#: Die Adresse von Magister, wie das Cockpit sie im Client einträgt. Keycloak
#: leitet den Browser dorthin zurück; der Test fängt die Umleitung ab und
#: reicht Code und State an die App weiter.
HOST = "kunde-a-um.example.ch"
REDIRECT = f"https://{HOST}/api/auth/callback"
USERNAME = "automato-admin"


@dataclass(frozen=True)
class Realm:
    base: str
    name: str
    issuer: str
    client_secret: str
    user_id: str
    password: str


def _keycloak() -> tuple[str, str, str]:
    base = os.environ.get("MAGISTER_TEST_KEYCLOAK_URL", "").strip().rstrip("/")
    if not base:
        pytest.skip("MAGISTER_TEST_KEYCLOAK_URL nicht gesetzt — kein Test gegen echten Keycloak")
    password = os.environ.get("MAGISTER_TEST_KEYCLOAK_ADMIN_PASSWORD", "")
    if not password:
        pytest.skip("MAGISTER_TEST_KEYCLOAK_ADMIN_PASSWORD nicht gesetzt")
    return base, os.environ.get("MAGISTER_TEST_KEYCLOAK_ADMIN", "admin"), password


async def _admin_token(kc: httpx.AsyncClient, user: str, password: str) -> str:
    resp = await kc.post(
        "/realms/master/protocol/openid-connect/token",
        data={
            "grant_type": "password",
            "client_id": "admin-cli",
            "username": user,
            "password": password,
        },
    )
    assert resp.status_code == 200, f"Admin-Anmeldung am Keycloak: HTTP {resp.status_code}"
    return str(resp.json()["access_token"])


def _cockpit_client(host: str) -> dict[str, Any]:
    """Der Client `magister`, wie das Cockpit ihn anlegt.

    Aus der Datei des Cockpits (`services/magister_anmeldung.py`: `adressen`,
    `neuer_client`), wenn der Checkout da ist — so fällt hier auf, wenn das
    Cockpit den Client anders anlegt, als Magister ihn braucht. Sonst die
    Abschrift vom 2026-11-16.
    """
    path = konsole_datei("services", "magister_anmeldung.py")
    if path is None:
        return {
            "clientId": "magister",
            "name": "Magister",
            "enabled": True,
            "protocol": "openid-connect",
            "publicClient": False,
            "clientAuthenticatorType": "client-secret",
            "standardFlowEnabled": True,
            "implicitFlowEnabled": False,
            "directAccessGrantsEnabled": False,
            "serviceAccountsEnabled": False,
            "frontchannelLogout": True,
            "redirectUris": [f"https://{host}/api/auth/callback"],
            "webOrigins": [f"https://{host}"],
            "attributes": {
                "pkce.code.challenge.method": "S256",
                "post.logout.redirect.uris": f"https://{host}/*",
            },
        }
    tree = ast.parse(path.read_text(encoding="utf-8"))
    wanted = {"CLIENT", "CALLBACK", "adressen", "neuer_client"}
    keep: list[ast.stmt] = []
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name in wanted:
            keep.append(node)
        elif isinstance(node, ast.Assign | ast.AnnAssign):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            if any(isinstance(t, ast.Name) and t.id in wanted for t in targets):
                keep.append(node)
    # Mit `annotations` wie im Cockpit: die Typen der Parameter (`Verknuepft`)
    # gibt es hier nicht, und sie werden so nicht ausgewertet.
    source = "from __future__ import annotations\n" + "\n".join(ast.unparse(n) for n in keep)
    namespace: dict[str, Any] = {"Any": Any}
    exec(compile(source, str(path), "exec"), namespace)  # noqa: S102
    linked = SimpleNamespace(tenant=SimpleNamespace(hostname=host))
    representation: dict[str, Any] = namespace["neuer_client"](namespace["adressen"]([linked]))
    return representation


@pytest_asyncio.fixture
async def realm() -> AsyncIterator[Realm]:
    """Ein frischer Realm mit dem Client des Cockpits und `automato-admin`."""
    base, admin_user, admin_password = _keycloak()
    name = f"magister-test-{secrets.token_hex(4)}"
    async with httpx.AsyncClient(base_url=base, timeout=30.0) as kc:
        kc.headers["Authorization"] = f"Bearer {await _admin_token(kc, admin_user, admin_password)}"
        created = await kc.post("/admin/realms", json={"realm": name, "enabled": True})
        assert created.status_code == 201, created.text
        try:
            client = await kc.post(f"/admin/realms/{name}/clients", json=_cockpit_client(HOST))
            assert client.status_code == 201, client.text
            client_id = client.headers["location"].rsplit("/", 1)[-1]
            secret = await kc.get(f"/admin/realms/{name}/clients/{client_id}/client-secret")
            assert secret.status_code == 200, secret.text
            password = secrets.token_urlsafe(18)
            user = await kc.post(
                f"/admin/realms/{name}/users",
                json={
                    "username": USERNAME,
                    "enabled": True,
                    "email": f"{USERNAME}@example.ch",
                    "emailVerified": True,
                    "firstName": "Automato",
                    "lastName": "Admin",
                    "credentials": [{"type": "password", "value": password, "temporary": False}],
                },
            )
            assert user.status_code == 201, user.text
            yield Realm(
                base=base,
                name=name,
                issuer=f"{base}/realms/{name}",
                client_secret=str(secret.json()["value"]),
                user_id=user.headers["location"].rsplit("/", 1)[-1],
                password=password,
            )
        finally:
            # Das Admin-Token lebt eine Minute; zum Aufräumen ein neues.
            kc.headers["Authorization"] = (
                f"Bearer {await _admin_token(kc, admin_user, admin_password)}"
            )
            await kc.delete(f"/admin/realms/{name}")


def _magister(app_settings: Settings, realm: Realm) -> Settings:
    """Die Einstellungen, die das Cockpit für diesen Realm setzt (`einstellungen`)."""
    return app_settings.model_copy(
        update={
            "oidc_issuer": realm.issuer,
            "oidc_client_id": "magister",
            "oidc_client_secret": SecretStr(realm.client_secret),
            "oidc_redirect_uri": REDIRECT,
            "oidc_scopes": ["openid", "profile", "email"],
            "bootstrap_admins": [USERNAME],
        }
    )


class _Browser:
    """Ein Browser für Keycloak: Cookies, keine automatischen Umleitungen.

    Keycloak setzt seine Cookies mit ``Secure``; die Cookie-Ablage schickt sie
    über http nicht zurück. Ein Browser tut es für ``127.0.0.1`` doch
    (localhost gilt als sicherer Ursprung) — deshalb hier nach jeder Antwort
    ``secure`` aus.
    """

    def __init__(self) -> None:
        self.http = httpx.AsyncClient(follow_redirects=False, timeout=30.0)

    async def __aenter__(self) -> _Browser:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.http.aclose()

    async def request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        resp = await self.http.request(method, url, **kwargs)
        for cookie in self.http.cookies.jar:
            cookie.secure = False
        return resp


def _form(resp: httpx.Response, form_id: str | None = None) -> tuple[str, dict[str, str]]:
    """Ziel (absolut) und versteckte Felder eines Formulars der Keycloak-Seite."""
    page = resp.text
    pattern = r"<form\b[^>]*>" if form_id is None else rf'<form\b[^>]*id="{form_id}"[^>]*>'
    tag = re.search(pattern, page)
    assert tag is not None, f"Formular nicht gefunden: {page[:300]}"
    action = re.search(r'action="([^"]+)"', tag.group(0))
    assert action is not None
    rest = page[tag.end() : page.find("</form>", tag.end())]
    hidden: dict[str, str] = {}
    for field in re.finditer(r"<input\b[^>]*>", rest):
        attrs = dict(re.findall(r'(\w+)="([^"]*)"', field.group(0)))
        if attrs.get("type") == "hidden" and "name" in attrs:
            hidden[attrs["name"]] = html.unescape(attrs.get("value", ""))
    return urljoin(str(resp.url), html.unescape(action.group(1))), hidden


def _sm(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False, autoflush=False)


class TestTheWholeWay:
    async def test_login_admin_and_logout_at_the_realm(
        self,
        app: FastAPI,
        client: AsyncClient,
        engine: AsyncEngine,
        app_settings: Settings,
        realm: Realm,
    ) -> None:
        settings = _magister(app_settings, realm)
        app.dependency_overrides[get_settings] = lambda: settings

        # 1. Magister schickt zum Anmeldeformular des Realms (Adresse aus der Discovery).
        login = await client.get("/auth/login")
        assert login.status_code == 303, login.text
        authorize = login.headers["location"]
        assert authorize.startswith(f"{realm.issuer}/protocol/openid-connect/auth?")
        params = parse_qs(urlsplit(authorize).query)
        assert params["code_challenge_method"] == ["S256"]
        assert params["redirect_uri"] == [REDIRECT]

        async with _Browser() as browser:
            # 2. Das Formular ausfüllen wie ein Mensch.
            page = await browser.request("GET", authorize)
            assert page.status_code == 200, page.text[:300]
            action, hidden = _form(page, "kc-form-login")
            back = await browser.request(
                "POST",
                action,
                data={**hidden, "username": USERNAME, "password": realm.password},
            )
            assert back.status_code == 302, back.text[:500]
            target = urlsplit(back.headers["location"])
            assert f"{target.scheme}://{target.netloc}{target.path}" == REDIRECT
            answer = parse_qs(target.query)

            # 3. Rückweg: Code-Tausch mit PKCE und Secret, ID-Token gegen die JWKS.
            callback = await client.get(
                "/auth/callback",
                params={"code": answer["code"][0], "state": answer["state"][0]},
            )
            assert callback.status_code == 303, callback.text
            assert callback.headers["location"] == "/"

            # 4. `automato-admin` ist Admin (bootstrap_admins), ohne Zeile im AD.
            me = await client.get("/auth/me")
            assert me.status_code == 200, me.text
            body = me.json()
            assert body["upn"] == USERNAME
            assert body["is_admin"] is True
            assert "admin" in body["roles"]
            assert body["display_name"] == "Automato Admin"
            async with _sm(engine)() as s:
                account = (
                    await s.execute(select(LoginAccount).where(LoginAccount.username == USERNAME))
                ).scalar_one()
            # Identität = iss + sub des echten Tokens (ADR-0025 D2).
            assert (account.issuer, account.subject) == (realm.issuer, realm.user_id)

            # 5. Abmelden: lokal weg, dazu die Abmeldeadresse des Realms.
            csrf = client.cookies.get("magister_csrf")
            assert csrf is not None
            out = await client.post("/auth/logout", headers={"X-CSRF-Token": csrf})
            assert out.status_code == 200, out.text
            redirect = urlsplit(out.json()["redirect"])
            assert f"{redirect.scheme}://{redirect.netloc}{redirect.path}" == (
                f"{realm.issuer}/protocol/openid-connect/logout"
            )
            assert parse_qs(redirect.query) == {
                "client_id": ["magister"],
                "post_logout_redirect_uri": [f"https://{HOST}/login"],
            }
            async with _sm(engine)() as s:
                assert (await s.execute(select(Session))).scalars().all() == []

            # 6. Keycloak nimmt die Rückkehradresse an (der Client des Cockpits
            #    erlaubt `https://<host>/*`), fragt einmal nach (kein
            #    `id_token_hint`) und schickt zurück auf `/login`.
            confirm = await browser.request("GET", out.json()["redirect"])
            assert confirm.status_code == 200, confirm.text[:500]
            action, hidden = _form(confirm)
            done = await browser.request("POST", action, data={**hidden, "confirmLogout": "x"})
            assert done.status_code == 302, done.text[:500]
            assert done.headers["location"] == f"https://{HOST}/login"

            # 7. Die Sitzung am Realm ist beendet: die nächste Anmeldung zeigt
            #    wieder das Formular, statt still anzumelden.
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://testserver"
            ) as fresh:
                assert (await fresh.get("/auth/me")).status_code == 401
                again = await fresh.get("/auth/login")
            page = await browser.request("GET", again.headers["location"])
            assert page.status_code == 200
            assert 'id="kc-form-login"' in page.text


class TestSelfCheckAgainstTheRealm:
    async def test_the_realm_is_in_order(self, app_settings: Settings, realm: Realm) -> None:
        result = await check_oidc(_magister(app_settings, realm))
        assert result["configured"] is True
        assert (result["ok"], result["reason"]) == (True, None)

    async def test_a_realm_that_does_not_exist(self, app_settings: Settings, realm: Realm) -> None:
        settings = _magister(app_settings, realm).model_copy(
            update={"oidc_issuer": f"{realm.base}/realms/{realm.name}-fehlt"}
        )
        result = await check_oidc(settings)
        host = urlsplit(realm.base).netloc
        assert (result["ok"], result["reason"]) == (False, f"discovery_http_404 ({host})")

    async def test_the_realm_names_itself_by_another_address(
        self, app_settings: Settings, realm: Realm
    ) -> None:
        """Wie im Fund: Magister fragt die interne Adresse, der Realm nennt die öffentliche."""
        base, admin_user, admin_password = _keycloak()
        async with httpx.AsyncClient(base_url=base, timeout=30.0) as kc:
            token = await _admin_token(kc, admin_user, admin_password)
            put = await kc.put(
                f"/admin/realms/{realm.name}",
                headers={"Authorization": f"Bearer {token}"},
                json={"attributes": {"frontendUrl": "https://auth.example.ch"}},
            )
            assert put.status_code == 204, put.text
        result = await check_oidc(_magister(app_settings, realm))
        host = urlsplit(realm.base).netloc
        assert result["ok"] is False
        assert result["reason"] == (
            f"issuer_mismatch: https://auth.example.ch/realms/{realm.name} ({host})"
        )

    async def test_without_the_client_secret(self, app_settings: Settings, realm: Realm) -> None:
        settings = _magister(app_settings, realm).model_copy(
            update={"oidc_client_secret": SecretStr("")}
        )
        result = await check_oidc(settings)
        assert (result["ok"], result["reason"]) == (False, "client_secret_missing")
