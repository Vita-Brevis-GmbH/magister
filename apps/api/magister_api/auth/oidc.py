"""OIDC client wrapper for Entra ID (Authorization Code + PKCE).

Heavy lifting is done by ``authlib``. This module exposes a small surface that
the auth router uses, plus a Protocol so tests can inject a mocked client.
"""

from __future__ import annotations

import base64
import hashlib
import secrets
from dataclasses import dataclass
from typing import Any, Protocol
from urllib.parse import urlencode

import httpx

from magister_api.config import Settings


@dataclass(frozen=True)
class OidcAuthorizeRequest:
    url: str
    state: str
    nonce: str
    code_verifier: str


@dataclass(frozen=True)
class OidcUserInfo:
    """Subset of id-token claims Magister needs."""

    subject: str
    upn: str
    oid: str | None
    given_name: str | None
    surname: str | None
    email: str | None


class OidcClient(Protocol):
    def build_authorize_request(self) -> OidcAuthorizeRequest: ...

    async def exchange_code(
        self, *, code: str, state: str, expected_state: str, code_verifier: str, nonce: str
    ) -> OidcUserInfo: ...


class EntraOidcClient:
    """Minimal OIDC client tailored for Entra ID."""

    def __init__(self, settings: Settings, http: httpx.AsyncClient | None = None) -> None:
        self._settings = settings
        self._http = http

    @property
    def http(self) -> httpx.AsyncClient:
        if self._http is None:
            self._http = httpx.AsyncClient(timeout=10.0)
        return self._http

    async def _discover(self) -> dict[str, Any]:
        url = f"{self._settings.oidc_issuer.rstrip('/')}/.well-known/openid-configuration"
        resp = await self.http.get(url)
        resp.raise_for_status()
        return resp.json()

    def build_authorize_request(self) -> OidcAuthorizeRequest:
        state = secrets.token_urlsafe(32)
        nonce = secrets.token_urlsafe(32)
        code_verifier = secrets.token_urlsafe(64)
        code_challenge = (
            base64.urlsafe_b64encode(hashlib.sha256(code_verifier.encode()).digest())
            .rstrip(b"=")
            .decode()
        )
        params = {
            "response_type": "code",
            "client_id": self._settings.oidc_client_id,
            "redirect_uri": self._settings.oidc_redirect_uri,
            "scope": " ".join(self._settings.oidc_scopes),
            "state": state,
            "nonce": nonce,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
        }
        url = f"{self._settings.oidc_issuer.rstrip('/')}/authorize?{urlencode(params)}"
        return OidcAuthorizeRequest(url=url, state=state, nonce=nonce, code_verifier=code_verifier)

    async def exchange_code(
        self,
        *,
        code: str,
        state: str,
        expected_state: str,
        code_verifier: str,
        nonce: str,
    ) -> OidcUserInfo:
        if not secrets.compare_digest(state, expected_state):
            raise ValueError("oidc_state_mismatch")

        meta = await self._discover()
        token_endpoint = meta["token_endpoint"]
        resp = await self.http.post(
            token_endpoint,
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": self._settings.oidc_redirect_uri,
                "client_id": self._settings.oidc_client_id,
                "client_secret": self._settings.oidc_client_secret.get_secret_value(),
                "code_verifier": code_verifier,
            },
            headers={"Accept": "application/json"},
        )
        resp.raise_for_status()
        token = resp.json()
        id_token = token.get("id_token")
        if not id_token:
            raise ValueError("oidc_no_id_token")

        # Decode without local JWKS validation: the issuer + signature check
        # belongs in a JWT-aware library. For initial scaffolding we trust the
        # backchannel TLS to Entra and the redirect-URI binding; full JWKS
        # validation is added when the OIDC integration is hardened.
        from authlib.jose import jwt as authlib_jwt

        meta_jwks_uri = meta["jwks_uri"]
        jwks_resp = await self.http.get(meta_jwks_uri)
        jwks_resp.raise_for_status()
        claims = authlib_jwt.decode(
            id_token,
            key=jwks_resp.json(),
            claims_options={
                "iss": {"essential": True, "value": meta.get("issuer", self._settings.oidc_issuer)},
                "aud": {"essential": True, "value": self._settings.oidc_client_id},
                "nonce": {"essential": True, "value": nonce},
            },
        )
        claims.validate()

        upn = (claims.get("preferred_username") or claims.get("upn") or "").strip().lower()
        if not upn:
            raise ValueError("oidc_missing_upn")
        return OidcUserInfo(
            subject=claims["sub"],
            upn=upn,
            oid=(claims.get("oid") or "").lower() or None,
            given_name=claims.get("given_name"),
            surname=claims.get("family_name"),
            email=claims.get("email"),
        )
