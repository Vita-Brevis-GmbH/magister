"""CSV-Import request/response schemas (M3 US-2)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


class ImportStagedRowOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    row_num: int
    raw_data: dict[str, Any]
    action: str
    errors: list[str]
    applied_at: datetime | None
    applied_error: str | None


class ImportJobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    school_id: int
    kind: str
    status: str
    filename: str | None
    created_by_upn: str | None
    created_at: datetime
    applied_at: datetime | None
    summary: dict[str, Any]


class ImportJobDetailOut(ImportJobOut):
    rows: list[ImportStagedRowOut]
    counts: dict[str, int]
    """Per-action counts (create/update/skip/error)."""


class ProvisionedCredentialOut(BaseModel):
    """One-time credential for a provisioned student (``students`` import).

    Returned exactly once in the apply response so the caller can render the
    hand-out PDFs. The password is never persisted or audited.
    """

    upn: str
    display_name: str
    class_name: str
    password: str
    force_change: bool


class ImportApplyResultOut(ImportJobDetailOut):
    credentials: list[ProvisionedCredentialOut] = []
    """Populated only for the ``students`` provisioning import; empty otherwise."""


__all__ = [
    "ImportApplyResultOut",
    "ImportJobDetailOut",
    "ImportJobOut",
    "ImportStagedRowOut",
    "ProvisionedCredentialOut",
]
