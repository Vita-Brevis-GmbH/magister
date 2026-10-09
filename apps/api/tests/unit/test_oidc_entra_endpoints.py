"""Die Anmeldeadresse kommt aus dem Discovery-Dokument von Entra.

Vorher wurde sie aus dem Issuer zusammengesetzt (`…/<tenant>/v2.0/authorize`).
Entra erwartet `…/<tenant>/oauth2/v2.0/authorize` — der Browser landete auf
einer Fehlerseite von Microsoft, bevor Magister überhaupt beteiligt war. Der
Test benutzt die echten Pfade, wie Entra sie im Discovery-Dokument nennt.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from magister_api.auth.oidc import EntraOidcClient

TENANT = "11111111-2222-3333-4444-555555555555"
ISSUER = f"https://login.microsoftonline.com/{TENANT}/v2.0"
DISCOVERY = {
    "issuer": ISSUER,
    "authorization_endpoint": f"https://login.microsoftonline.com/{TENANT}/oauth2/v2.0/authorize",
    "token_endpoint": f"https://login.microsoftonline.com/{TENANT}/oauth2/v2.0/token",
    "jwks_uri": f"https://login.microsoftonline.com/{TENANT}/discovery/v2.0/keys",
}


def _client(handler: Any) -> EntraOidcClient:
    settings: Any = SimpleNamespace(
        oidc_issuer=ISSUER,
        oidc_client_id="client-1",
        oidc_redirect_uri="https://gmp.dev.test/api/auth/callback",
        oidc_scopes=["openid", "profile", "email"],
    )
    client = EntraOidcClient(settings)
    client._http = httpx.AsyncClient(transport=httpx.MockTransport(handler))  # type: ignore[attr-defined]
    return client


@pytest.mark.asyncio
async def test_the_authorize_url_is_entras_own() -> None:
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
    assert params["redirect_uri"] == ["https://gmp.dev.test/api/auth/callback"]
    assert params["code_challenge_method"] == ["S256"]
    assert params["scope"] == ["openid profile email"]


@pytest.mark.asyncio
async def test_an_unreachable_or_wrong_tenant_is_a_code_not_a_crash() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": "invalid_tenant"})

    with pytest.raises(ValueError, match="oidc_discovery_failed"):
        await _client(handler).build_authorize_request()


@pytest.mark.asyncio
async def test_a_wrong_client_secret_is_a_code_not_a_500() -> None:
    """AADSTS7000215 (falsches Secret) oder 50011 (Umleitungs-URI) beim Code-Tausch."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/.well-known/openid-configuration"):
            return httpx.Response(200, json=DISCOVERY)
        return httpx.Response(
            401,
            json={
                "error": "invalid_client",
                "error_description": "AADSTS7000215: Invalid client secret provided.",
                "error_codes": [7000215],
            },
        )

    client = _client(handler)
    client._settings.oidc_client_secret = SimpleNamespace(get_secret_value=lambda: "falsch")  # type: ignore[attr-defined]
    with pytest.raises(ValueError, match="oidc_token_exchange_failed"):
        await client.exchange_code(
            code="c", state="s", expected_state="s", code_verifier="v", nonce="n"
        )
