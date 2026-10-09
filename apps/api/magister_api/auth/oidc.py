"""OIDC client wrapper for Entra ID (Authorization Code + PKCE).

Heavy lifting is done by ``authlib``. This module exposes a small surface that
the auth router uses, plus a Protocol so tests can inject a mocked client.
"""

from __future__ import annotations

import base64
import hashlib
import logging
import secrets
from dataclasses import dataclass
from typing import Any, Protocol, cast
from urllib.parse import urlencode

import httpx

from magister_api.config import Settings

logger = logging.getLogger(__name__)


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
    async def build_authorize_request(self) -> OidcAuthorizeRequest: ...

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
        try:
            resp = await self.http.get(url)
            resp.raise_for_status()
            meta: Any = resp.json()
        except (httpx.HTTPError, ValueError) as exc:
            # Falsche Tenant-Id, kein Netz zu login.microsoftonline.com: ein
            # Code, den die Anmeldeseite übersetzt — kein 500.
            raise ValueError("oidc_discovery_failed") from exc
        if not isinstance(meta, dict):
            raise ValueError("oidc_discovery_failed")
        return cast(dict[str, Any], meta)

    async def build_authorize_request(self) -> OidcAuthorizeRequest:
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
        # Der Endpunkt kommt aus dem Discovery-Dokument, nicht aus dem Issuer:
        # bei Entra ist der Issuer `…/<tenant>/v2.0`, der Endpunkt aber
        # `…/<tenant>/oauth2/v2.0/authorize`. Aus dem Issuer zusammengesetzt
        # landete der Browser auf einer Seite, die es nicht gibt.
        meta = await self._discover()
        endpoint = str(
            meta.get("authorization_endpoint")
            or f"{self._settings.oidc_issuer.rstrip('/')}/authorize"
        )
        url = f"{endpoint}?{urlencode(params)}"
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
        try:
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
        except httpx.HTTPError as exc:
            raise ValueError("oidc_token_exchange_failed") from exc
        if resp.status_code != 200:
            # Entra nennt den Grund als AADSTS-Code (z. B. 7000215: falsches
            # Client-Secret, 50011: Umleitungs-URI passt nicht). Ins Protokoll
            # nur Code und Fehlerart — die Beschreibung kann Kennungen tragen.
            body: Any = {}
            try:
                body = resp.json()
            except ValueError:
                body = {}
            codes = body.get("error_codes") if isinstance(body, dict) else None
            logger.warning(
                "Entra hat den Code-Tausch abgewiesen: HTTP %s, %s, AADSTS %s",
                resp.status_code,
                body.get("error") if isinstance(body, dict) else "-",
                codes,
            )
            raise ValueError("oidc_token_exchange_failed")
        token = resp.json()
        id_token = token.get("id_token")
        if not id_token:
            raise ValueError("oidc_no_id_token")

        # Signatur gegen die JWKS aus dem Discovery-Dokument, dazu iss, aud
        # und nonce — authlib prüft alle vier.
        from authlib.jose import jwt as authlib_jwt
        from authlib.jose.errors import JoseError

        try:
            jwks_resp = await self.http.get(meta["jwks_uri"])
            jwks_resp.raise_for_status()
            claims = authlib_jwt.decode(
                id_token,
                key=jwks_resp.json(),
                claims_options={
                    "iss": {
                        "essential": True,
                        "value": meta.get("issuer", self._settings.oidc_issuer),
                    },
                    "aud": {"essential": True, "value": self._settings.oidc_client_id},
                    "nonce": {"essential": True, "value": nonce},
                },
            )
            claims.validate()
        except (httpx.HTTPError, JoseError) as exc:
            logger.warning("ID-Token von Entra nicht gültig: %s", type(exc).__name__)
            raise ValueError("oidc_token_invalid") from exc

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
