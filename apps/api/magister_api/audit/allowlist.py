"""Audit-payload safety guard.

Rejects payloads that contain forbidden keys (passwords, tokens, secrets, …)
*before* they are encrypted and written to ``audit_events.payload``.

Defense in depth: even though the column is encrypted-at-rest, plaintext
secrets must NEVER reach the column — leaked decryption keys would otherwise
expose them, and operators with legitimate decrypt access should not be able
to harvest student passwords from history.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

FORBIDDEN_KEY_PARTS: tuple[str, ...] = (
    "password",
    "passwort",
    "pwd",
    "secret",
    "token",
    "authorization",
    "cookie",
    "session_id",
    "csrf",
    "client_secret",
    "bind_password",
    "unicodepwd",
    "manual_password",
    "temp_password",
    "new_password",
    "id_token",
    "access_token",
    "refresh_token",
)

# Heuristics that catch credential-like values even if the key name is innocent.
_BEARER_RE = re.compile(r"(?i)bearer\s+[A-Za-z0-9._\-]{8,}")
_JWT_RE = re.compile(r"\beyJ[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+\b")
_PWD_KV_RE = re.compile(r"(?i)\b(password|passwort|pwd)\s*[:=]\s*\S+")

MAX_DEPTH = 6
MAX_VALUE_LEN = 4096


class SecretInPayloadError(ValueError):
    """Raised when an audit payload would leak a secret."""


def _key_is_forbidden(key: str) -> bool:
    k = key.lower()
    return any(part in k for part in FORBIDDEN_KEY_PARTS)


def _value_looks_secretish(value: str) -> bool:
    if _BEARER_RE.search(value):
        return True
    if _JWT_RE.search(value):
        return True
    if _PWD_KV_RE.search(value):
        return True
    return False


def validate_audit_payload(payload: Mapping[str, Any], *, _depth: int = 0) -> None:
    """Validate an audit payload. Raises ``SecretInPayloadError`` on violation.

    Rules:
    - No keys whose lowercase form contains any FORBIDDEN_KEY_PARTS substring.
    - No string values that match Bearer/JWT/credential-kv patterns.
    - Depth and value-length limits to keep the encrypted blob bounded.
    - Only JSON-serialisable scalar/container types.
    """
    if _depth > MAX_DEPTH:
        raise SecretInPayloadError(f"audit payload exceeds depth {MAX_DEPTH}")

    for raw_key, value in payload.items():
        if not isinstance(raw_key, str):  # pyright: ignore[reportUnnecessaryIsInstance]
            # Belt-and-braces — Mapping[str, Any] does not actually enforce str at runtime.
            raise SecretInPayloadError(
                f"audit payload keys must be str, got {type(raw_key).__name__}"
            )
        if _key_is_forbidden(raw_key):
            raise SecretInPayloadError(f"forbidden key in audit payload: {raw_key!r}")
        _validate_value(raw_key, value, _depth=_depth + 1)


def _validate_value(key: str, value: Any, *, _depth: int) -> None:
    if value is None or isinstance(value, (bool, int, float)):
        return
    if isinstance(value, str):
        if len(value) > MAX_VALUE_LEN:
            raise SecretInPayloadError(f"value at {key!r} exceeds {MAX_VALUE_LEN} chars")
        if _value_looks_secretish(value):
            raise SecretInPayloadError(
                f"value at {key!r} looks like a credential — refusing to log"
            )
        return
    if isinstance(value, Mapping):
        validate_audit_payload(value, _depth=_depth)
        return
    if isinstance(value, (list, tuple)):
        for i, item in enumerate(value):
            _validate_value(f"{key}[{i}]", item, _depth=_depth + 1)
        return
    raise SecretInPayloadError(f"value at {key!r} has unsupported type {type(value).__name__}")
