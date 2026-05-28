"""Schemas for the M2 user-lifecycle endpoint (``PATCH /users/{guid}/status``)."""

from __future__ import annotations

from pydantic import BaseModel, Field


class UserStatusUpdate(BaseModel):
    """Request body for enable/disable.

    The optional ``reason`` lands in the audit payload — keep it short and
    free of credentials (the audit allowlist would refuse common credential
    keys, but the reason field is free-form text and not redacted, so callers
    must not paste passwords or tokens here).
    """

    enabled: bool
    reason: str | None = Field(default=None, max_length=500)
