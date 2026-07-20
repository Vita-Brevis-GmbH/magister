"""Response schemas for the System-operations endpoints."""

from __future__ import annotations

from pydantic import BaseModel


class SystemCommandResult(BaseModel):
    """Last outcome as written by the host watcher into status.json."""

    action: str | None = None
    state: str | None = None  # queued | running | success | error
    message: str | None = None
    git_sha: str | None = None
    started_at: str | None = None
    finished_at: str | None = None


class SystemStatusOut(BaseModel):
    configured: bool
    pending: int = 0
    last: SystemCommandResult | None = None
    # Live combined output of the most recent command (tail), or None.
    log: str | None = None


class SystemCommandResponse(BaseModel):
    id: str
    action: str
    requested_at: str


__all__ = ["SystemCommandResponse", "SystemCommandResult", "SystemStatusOut"]
