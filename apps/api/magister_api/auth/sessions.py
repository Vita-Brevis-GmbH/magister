"""Session-id generation utilities."""

from __future__ import annotations

import secrets

SESSION_ID_BYTES = 32  # 256-bit opaque token


def new_session_id() -> str:
    """Return a URL-safe random session id of ``SESSION_ID_BYTES`` entropy."""
    return secrets.token_urlsafe(SESSION_ID_BYTES)
