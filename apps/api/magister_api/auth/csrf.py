"""CSRF protection: signed double-submit cookie + ``X-CSRF-Token`` header.

For mutating requests (POST/PUT/PATCH/DELETE), the middleware verifies that the
cookie value and header value match and the value is a valid HMAC of the
session-id prefix. GET/HEAD/OPTIONS are exempted.
"""

from __future__ import annotations

import hmac
import secrets
from collections.abc import Awaitable, Callable
from hashlib import sha256

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from magister_api.config import Settings, get_settings

SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


def _hmac(secret: str, message: str) -> str:
    return hmac.new(secret.encode("utf-8"), message.encode("utf-8"), sha256).hexdigest()


def issue_csrf_token(session_id: str, settings: Settings | None = None) -> str:
    """Generate a CSRF token bound to ``session_id``.

    Format: ``<nonce>.<hmac(secret, session_id+nonce)>``. The token is opaque
    to the client and is verified by recomputing the HMAC.
    """
    s = settings or get_settings()
    secret = s.csrf_secret.get_secret_value()
    if not secret:
        raise RuntimeError("MAGISTER_CSRF_SECRET is empty")
    nonce = secrets.token_urlsafe(16)
    mac = _hmac(secret, f"{session_id}.{nonce}")
    return f"{nonce}.{mac}"


def verify_csrf_token(token: str, session_id: str, settings: Settings | None = None) -> bool:
    s = settings or get_settings()
    secret = s.csrf_secret.get_secret_value()
    if not secret:
        return False
    try:
        nonce, mac = token.split(".", 1)
    except ValueError:
        return False
    expected = _hmac(secret, f"{session_id}.{nonce}")
    return hmac.compare_digest(mac, expected)


class CsrfMiddleware(BaseHTTPMiddleware):
    """Enforce double-submit + HMAC for unsafe methods on protected paths.

    Endpoints under ``/auth/login`` and ``/auth/callback`` are exempt because
    they pre-date the session. ``/auth/logout`` is exempt too: it still
    requires a valid session cookie (``get_current_user``), forging it is only
    a nuisance (it logs the victim out), and requiring a matching CSRF token
    there means a stale ``magister_csrf`` cookie silently blocks sign-out.
    """

    EXEMPT_PATH_PREFIXES = ("/auth/login", "/auth/logout", "/auth/callback", "/healthz")

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        if request.method in SAFE_METHODS:
            return await call_next(request)
        if any(request.url.path.startswith(p) for p in self.EXEMPT_PATH_PREFIXES):
            return await call_next(request)

        settings: Settings = getattr(request.app.state, "settings", None) or get_settings()
        cookie = request.cookies.get(settings.csrf_cookie_name)
        header = request.headers.get(settings.csrf_header_name)
        session_cookie = request.cookies.get(settings.session_cookie_name)
        if not cookie or not header or not session_cookie:
            return JSONResponse(status_code=403, content={"detail": "csrf_missing"})
        if not hmac.compare_digest(cookie, header):
            return JSONResponse(status_code=403, content={"detail": "csrf_mismatch"})
        if not verify_csrf_token(cookie, session_cookie, settings):
            return JSONResponse(status_code=403, content={"detail": "csrf_invalid"})
        return await call_next(request)
