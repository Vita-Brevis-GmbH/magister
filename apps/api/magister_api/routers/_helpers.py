"""Shared helpers for HTTP routers."""

from __future__ import annotations

from fastapi import Request


def _ip_request_id(request: Request) -> tuple[str | None, str]:
    """Return the client IP and request id stashed on ``request.state``.

    Both are populated by the audit middleware; missing values fall back to
    ``None`` / ``""`` so callers can always unpack the tuple.
    """
    return (
        getattr(request.state, "client_ip", None),
        getattr(request.state, "request_id", ""),
    )
