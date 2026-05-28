"""Pydantic schemas for the audit-listing endpoint (M2 US-7)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


class AuditEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    ts: datetime
    actor_upn: str | None
    actor_object_guid: str | None
    action: str
    target_kind: str
    target_id: str
    school_id: int | None
    ip: str | None
    request_id: str
    payload: dict[str, Any]


class AuditEventListResponse(BaseModel):
    items: list[AuditEventOut]
    total: int
    offset: int
    limit: int
