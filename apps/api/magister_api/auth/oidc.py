"""OIDC client (Authorization Code + PKCE) for the customer's Keycloak realm.

Since ADR-0025 every end user signs in at the customer's Keycloak realm; which
directory stands behind it (local users, Entra, LDAP) is configured there and
is invisible here. The client is plain OIDC: discovery, PKCE, JWKS, and the
checks on ``iss``/``aud``/``nonce`` — nothing provider-specific.

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
from urllib.parse import urlencode, urlsplit

import httpx

from magister_api.config import Settings
from magister_api.schemas.common import validate_login_name

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class OidcAuthorizeRequest:
    url: str
    state: str
    nonce: str
    code_verifier: str


@dataclass(frozen=True)
class OidcUserInfo:
    """Subset of id-token claims Magister needs (ADR-0025).

    The identity is ``issuer`` + ``subject``; ``username`` is the
    ``preferred_username`` of the realm, already lower-cased and checked
    against the login-name rule.
    """

    issuer: str
    subject: str
    username: str
    display_name: str | None
    given_name: str | None
    surname: str | None
    email: str | None


class OidcClient(Protocol):
    async def build_authorize_request(self) -> OidcAuthorizeRequest: ...

    async def exchange_code(
        self, *, code: str, state: str, expected_state: str, code_verifier: str, nonce: str
    ) -> OidcUserInfo: ...

    async def end_session_url(self) -> str | None: ...


def post_logout_redirect_uri(redirect_uri: str) -> str | None:
    """``https://<host>/login`` — the origin of the configured callback.

    Taken from ``oidc_redirect_uri`` (set by the console) and not from the
    request's ``Host`` header: a header the client controls must not decide
    where the identity provider sends the browser next.
    """
    parts = urlsplit(redirect_uri)
    if parts.scheme not in {"http", "https"} or not parts.netloc:
        return None
    return f"{parts.scheme}://{parts.netloc}/login"


class StandardOidcClient:
    """Minimal standards-based OIDC client (discovery, PKCE, JWKS)."""

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
            # Falscher Realm im Issuer, kein Netz zum Anbieter: ein Code, den
            # die Anmeldeseite übersetzt — kein 500.
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
        # bei Keycloak ist er `…/realms/<realm>/protocol/openid-connect/auth`,
        # bei anderen Anbietern wieder anders. Aus dem Issuer zusammengesetzt
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
            # Ins Protokoll nur HTTP-Status und Fehlerart nach RFC 6749
            # (`invalid_client`, `invalid_grant` …) — die Beschreibung kann
            # Kennungen tragen und bleibt draussen.
            body: Any = {}
            try:
                body = resp.json()
            except ValueError:
                body = {}
            error = body.get("error") if isinstance(body, dict) else None
            logger.warning(
                "Der Anbieter hat den Code-Tausch abgewiesen: HTTP %s, %s",
                resp.status_code,
                error if isinstance(error, str) and error.isidentifier() else "-",
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
            logger.warning("ID-Token des Anbieters nicht gültig: %s", type(exc).__name__)
            raise ValueError("oidc_token_invalid") from exc

        raw_username = claims.get("preferred_username")
        try:
            username = validate_login_name(raw_username if isinstance(raw_username, str) else "")
        except ValueError as exc:
            raise ValueError("oidc_missing_username") from exc
        subject = claims.get("sub")
        if not isinstance(subject, str) or not subject:
            raise ValueError("oidc_token_invalid")
        return OidcUserInfo(
            issuer=str(claims.get("iss") or meta.get("issuer") or self._settings.oidc_issuer),
            subject=subject,
            username=username,
            display_name=_text(claims.get("name")),
            given_name=_text(claims.get("given_name")),
            surname=_text(claims.get("family_name")),
            email=_text(claims.get("email"), limit=320),
        )

    async def end_session_url(self) -> str | None:
        """Where the browser goes after the local session is gone (ADR-0025).

        The ``end_session_endpoint`` of the discovery document, with
        ``client_id`` and ``post_logout_redirect_uri`` — without
        ``id_token_hint``: Magister keeps no token after the login. Keycloak
        then asks once whether to sign out, and that is acceptable. ``None``
        when the provider names no such endpoint or is unreachable; the local
        logout has already happened and must not fail on this.
        """
        try:
            meta = await self._discover()
        except ValueError:
            logger.warning("Abmelden beim Anbieter: Discovery nicht erreichbar")
            return None
        endpoint = meta.get("end_session_endpoint")
        if not isinstance(endpoint, str) or not endpoint.startswith(("https://", "http://")):
            return None
        params = {"client_id": self._settings.oidc_client_id}
        back = post_logout_redirect_uri(self._settings.oidc_redirect_uri)
        if back is not None:
            params["post_logout_redirect_uri"] = back
        return f"{endpoint}?{urlencode(params)}"


def _text(value: Any, *, limit: int = 200) -> str | None:
    """A claim as trimmed text, or ``None`` (claims are untrusted input)."""
    if not isinstance(value, str):
        return None
    v = value.strip()
    return v[:limit] or None
