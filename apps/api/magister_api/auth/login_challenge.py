"""Short-lived, stateless proof that a password was just verified (ADR-0015 D2).

The local login is two steps: password, then second factor. Between them the
server must remember "this password checked out" without keeping the password
around and without re-asking for it.

A signed challenge does that with no server state: HMAC over the account, the
stage and an expiry, signed with ``MAGISTER_SESSION_SECRET``. It is worthless
on its own — it only becomes a session together with a valid, unused TOTP code,
and codes are single-use (``local_admins.totp_last_step``), which is what
bounds replay.
"""

from __future__ import annotations

import base64
import hmac
import json
import secrets
import time
from hashlib import sha256

from magister_api.config import Settings

#: Long enough to fetch a phone, short enough to be uninteresting to steal.
CHALLENGE_TTL_SECONDS = 300


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _sign(secret: str, body: bytes) -> str:
    return _b64(hmac.new(secret.encode("utf-8"), body, sha256).digest())


def issue(*, username: str, stage: str, settings: Settings, now: float | None = None) -> str:
    """Mint a challenge for *username* at *stage* (``totp`` or ``enroll``)."""
    secret = settings.session_secret.get_secret_value()
    if not secret:
        raise RuntimeError("MAGISTER_SESSION_SECRET is empty — login challenge refused")
    issued = time.time() if now is None else now
    body = json.dumps(
        {
            "u": username,
            "s": stage,
            "e": int(issued + CHALLENGE_TTL_SECONDS),
            "n": secrets.token_urlsafe(8),
        },
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return f"{_b64(body)}.{_sign(secret, body)}"


def verify(
    challenge: str, *, stage: str, settings: Settings, now: float | None = None
) -> str | None:
    """Return the username the challenge was minted for, or ``None``.

    ``None`` covers every failure — bad signature, wrong stage, expired,
    malformed — on purpose: the caller has nothing useful to tell apart, and a
    single answer keeps the endpoint from becoming an oracle.
    """
    secret = settings.session_secret.get_secret_value()
    if not secret:
        return None
    try:
        payload, mac = challenge.split(".", 1)
        body = _unb64(payload)
    except (ValueError, TypeError):
        return None
    if not hmac.compare_digest(mac, _sign(secret, body)):
        return None
    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict) or data.get("s") != stage:
        return None
    expires = data.get("e")
    if not isinstance(expires, int) or expires < (time.time() if now is None else now):
        return None
    username = data.get("u")
    return username if isinstance(username, str) and username else None


__all__ = ["CHALLENGE_TTL_SECONDS", "issue", "verify"]
