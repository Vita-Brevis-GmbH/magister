"""Structured JSON logging with hard-coded secret redaction.

Magister CLAUDE.md "Niemals"-Regeln:
- Keine Credentials, Passwörter, Session-Tokens, OIDC-Token, LDAP-Bind-Strings im Log.
- Keine `print()` im Backend.

This module wires stdlib logging to emit single-line JSON and applies a
filter that redacts forbidden substrings/keys before they touch a handler.
"""

from __future__ import annotations

import json
import logging
import re
import sys
from collections.abc import Mapping
from typing import Any

REDACTED = "***REDACTED***"

# Substring match (case-insensitive) on field names + on free-form messages.
FORBIDDEN_KEY_PARTS: tuple[str, ...] = (
    "password",
    "passwort",
    "secret",
    "token",
    "authorization",
    "cookie",
    "set-cookie",
    "client_secret",
    "csrf",
    "session_id",
    "bind_password",
    "ldap_password",
    "unicodepwd",
)

# Patterns for credential-like values in free text.
_BEARER_RE = re.compile(r"(?i)bearer\s+[A-Za-z0-9._\-]+")
_BIND_DN_PW_RE = re.compile(r"(?i)(password|passwort|pwd)\s*[:=]\s*\S+")


def _is_forbidden_key(key: str) -> bool:
    k = key.lower()
    return any(part in k for part in FORBIDDEN_KEY_PARTS)


def _redact_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            k: (REDACTED if _is_forbidden_key(k) else _redact_value(v)) for k, v in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_redact_value(v) for v in value]
    if isinstance(value, str):
        v = _BEARER_RE.sub(f"Bearer {REDACTED}", value)
        v = _BIND_DN_PW_RE.sub(rf"\1={REDACTED}", v)
        return v
    return value


class SecretRedactionFilter(logging.Filter):
    """Filter that redacts forbidden keys from `extra` and the formatted message."""

    def filter(self, record: logging.LogRecord) -> bool:
        # Redact attributes that could carry payloads (extra=...).
        for attr_name, attr_value in list(record.__dict__.items()):
            if attr_name in _RESERVED_LOGRECORD_ATTRS:
                continue
            if _is_forbidden_key(attr_name):
                setattr(record, attr_name, REDACTED)
            else:
                setattr(record, attr_name, _redact_value(attr_value))
        # Redact the message itself (covers .getMessage() output).
        if isinstance(record.msg, str):
            record.msg = _redact_value(record.msg)
        return True


_RESERVED_LOGRECORD_ATTRS: frozenset[str] = frozenset(
    {
        "name",
        "msg",
        "args",
        "levelname",
        "levelno",
        "pathname",
        "filename",
        "module",
        "exc_info",
        "exc_text",
        "stack_info",
        "lineno",
        "funcName",
        "created",
        "msecs",
        "relativeCreated",
        "thread",
        "threadName",
        "processName",
        "process",
        "message",
        "asctime",
    }
)


class JsonFormatter(logging.Formatter):
    """Formats log records as single-line JSON."""

    def format(self, record: logging.LogRecord) -> str:
        out: dict[str, Any] = {
            "ts": self.formatTime(record, datefmt="%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        if record.exc_info:
            out["exc"] = self.formatException(record.exc_info)
        for k, v in record.__dict__.items():
            if k in _RESERVED_LOGRECORD_ATTRS:
                continue
            try:
                json.dumps(v)
                out[k] = v
            except (TypeError, ValueError):
                out[k] = repr(v)
        return json.dumps(out, ensure_ascii=False)


def configure_logging(level: str = "INFO") -> None:
    """Configure root logger with JSON handler + redaction filter."""
    root = logging.getLogger()
    for h in list(root.handlers):
        root.removeHandler(h)
    handler = logging.StreamHandler(stream=sys.stdout)
    handler.setFormatter(JsonFormatter())
    handler.addFilter(SecretRedactionFilter())
    root.addHandler(handler)
    root.setLevel(level.upper())
    # Quiet third-party noise.
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
