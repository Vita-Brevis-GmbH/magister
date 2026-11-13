"""Der OIDC-Client gegen ein Keycloak-förmiges Discovery-Dokument (ADR-0025).

Die Anmeldeadresse kommt aus dem Discovery-Dokument und wird nicht aus dem
Issuer zusammengesetzt — bei Keycloak heisst sie
`…/realms/<realm>/protocol/openid-connect/auth`. Dazu der Code-Tausch mit
einem echt signierten ID-Token (Benutzername ohne `@`), die Fehlercodes und
die Abmeldeadresse.
"""

from __future__ import annotations

import time
from types import SimpleNamespace
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from authlib.jose import JsonWebKey, jwt

from magister_api.auth.oidc import StandardOidcClient, post_logout_redirect_uri

ISSUER = "https://sso.example.ch/realms/kunde-a"
BASE = f"{ISSUER}/protocol/openid-connect"
DISCOVERY = {
    "issuer": ISSUER,
    "authorization_endpoint": f"{BASE}/auth",
    "token_endpoint": f"{BASE}/token",
    "jwks_uri": f"{BASE}/certs",
    "end_session_endpoint": f"{BASE}/logout",
}
CLIENT_ID = "magister"
REDIRECT = "https://kunde-a-um.example.ch/api/auth/callback"

_KEY = JsonWebKey.generate_key("RSA", 2048, is_private=True, options={"kid": "k1"})


def _client(handler: Any) -> StandardOidcClient:
    settings: Any = SimpleNamespace(
        oidc_issuer=ISSUER,
        oidc_client_id=CLIENT_ID,
        oidc_client_secret=SimpleNamespace(get_secret_value=lambda: "geheim"),
        oidc_redirect_uri=REDIRECT,
        oidc_scopes=["openid", "profile", "email"],
    )
    client = StandardOidcClient(settings)
    client._http = httpx.AsyncClient(transport=httpx.MockTransport(handler))  # type: ignore[attr-defined]
    return client


def _id_token(**claims: Any) -> str:
    now = int(time.time())
    body: dict[str, Any] = {
        "iss": ISSUER,
        "aud": CLIENT_ID,
        "sub": "0b5e6f0e-1111-2222-3333-444455556666",
        "nonce": "n",
        "iat": now,
        "exp": now + 300,
        "preferred_username": "automato-admin",
        "name": "Automato Admin",
    }
    body.update(claims)
    body = {k: v for k, v in body.items() if v is not None}
    return jwt.encode({"alg": "RS256", "kid": "k1"}, body, _KEY).decode()


def _provider(id_token: str) -> Any:
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/.well-known/openid-configuration"):
            return httpx.Response(200, json=DISCOVERY)
        if path.endswith("/token"):
            return httpx.Response(200, json={"id_token": id_token, "access_token": "a"})
        if path.endswith("/certs"):
            return httpx.Response(200, json={"keys": [_KEY.as_dict(is_private=False)]})
        return httpx.Response(404)

    return handler


async def _exchange(client: StandardOidcClient) -> Any:
    return await client.exchange_code(
        code="c", state="s", expected_state="s", code_verifier="v", nonce="n"
    )


@pytest.mark.asyncio
async def test_the_authorize_url_comes_from_discovery() -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return httpx.Response(200, json=DISCOVERY)

    req = await _client(handler).build_authorize_request()
    url = urlparse(req.url)
    assert f"{url.scheme}://{url.netloc}{url.path}" == DISCOVERY["authorization_endpoint"]
    assert seen == [f"{ISSUER}/.well-known/openid-configuration"]
    params = parse_qs(url.query)
    assert params["response_type"] == ["code"]
    assert params["client_id"] == [CLIENT_ID]
    assert params["redirect_uri"] == [REDIRECT]
    assert params["code_challenge_method"] == ["S256"]
    assert params["scope"] == ["openid profile email"]


@pytest.mark.asyncio
async def test_an_unreachable_or_wrong_realm_is_a_code_not_a_crash() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"error": "Realm does not exist"})

    with pytest.raises(ValueError, match="oidc_discovery_failed"):
        await _client(handler).build_authorize_request()


@pytest.mark.asyncio
async def test_a_wrong_client_secret_is_a_code_not_a_500() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/.well-known/openid-configuration"):
            return httpx.Response(200, json=DISCOVERY)
        return httpx.Response(
            401,
            json={"error": "unauthorized_client", "error_description": "Invalid client secret"},
        )

    with pytest.raises(ValueError, match="oidc_token_exchange_failed"):
        await _exchange(_client(handler))


@pytest.mark.asyncio
async def test_the_user_name_needs_no_at_and_the_identity_is_issuer_plus_subject() -> None:
    info = await _exchange(_client(_provider(_id_token(preferred_username="Automato-Admin"))))
    assert info.issuer == ISSUER
    assert info.subject == "0b5e6f0e-1111-2222-3333-444455556666"
    assert info.username == "automato-admin"
    assert info.display_name == "Automato Admin"


@pytest.mark.asyncio
async def test_no_oid_and_no_upn_claim_are_needed() -> None:
    # Keycloak schickt weder `oid` noch `upn` — und das ist kein Fehler mehr.
    info = await _exchange(_client(_provider(_id_token(email="a@example.ch"))))
    assert info.email == "a@example.ch"


@pytest.mark.asyncio
@pytest.mark.parametrize("name", [None, "", "mit leer"])
async def test_a_missing_or_invalid_user_name_is_a_code(name: str | None) -> None:
    client = _client(_provider(_id_token(preferred_username=name)))
    with pytest.raises(ValueError, match="oidc_missing_username"):
        await _exchange(client)


@pytest.mark.asyncio
async def test_a_token_for_another_client_is_refused() -> None:
    client = _client(_provider(_id_token(aud="anderer-client")))
    with pytest.raises(ValueError, match="oidc_token_invalid"):
        await _exchange(client)


@pytest.mark.asyncio
async def test_the_end_session_url_names_client_and_way_back() -> None:
    url = await _client(_provider("")).end_session_url()
    assert url is not None
    parsed = urlparse(url)
    assert f"{parsed.scheme}://{parsed.netloc}{parsed.path}" == DISCOVERY["end_session_endpoint"]
    params = parse_qs(parsed.query)
    assert params == {
        "client_id": [CLIENT_ID],
        "post_logout_redirect_uri": ["https://kunde-a-um.example.ch/login"],
    }


@pytest.mark.asyncio
async def test_no_end_session_endpoint_means_no_redirect() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        meta = {k: v for k, v in DISCOVERY.items() if k != "end_session_endpoint"}
        return httpx.Response(200, json=meta)

    assert await _client(handler).end_session_url() is None


@pytest.mark.asyncio
async def test_an_unreachable_provider_does_not_break_the_logout() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("kein Netz")

    assert await _client(handler).end_session_url() is None


def test_the_way_back_is_the_origin_of_the_callback() -> None:
    assert post_logout_redirect_uri(REDIRECT) == "https://kunde-a-um.example.ch/login"
    assert post_logout_redirect_uri("http://localhost:8000/auth/callback") == (
        "http://localhost:8000/login"
    )
    assert post_logout_redirect_uri("") is None
    assert post_logout_redirect_uri("javascript:alert(1)") is None
