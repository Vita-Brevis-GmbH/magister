"""AD-User listing schemas."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class AdUserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    ad_object_guid: str
    school_id: int | None
    upn: str
    sam_account_name: str | None = None
    given_name: str | None
    surname: str | None
    display_name: str | None = None
    mail: str | None
    kind: str
    enabled: bool
    last_sync_at: datetime | None
    street_address: str | None = None
    locality: str | None = None
    postal_code: str | None = None
    country: str | None = None
    device_name: str | None = None
    temp_device_name: str | None = None
    jahrgangsstufe: int | None = None


class AdUserListResponse(BaseModel):
    items: list[AdUserOut]
    total: int = Field(..., description="Total rows matching the filter (pagination-independent).")
    offset: int
    limit: int
    last_sync_at: datetime | None = Field(
        default=None,
        description="Most recent ad_user_cache.last_sync_at across the user's school scope.",
    )


class AdSyncResultOut(BaseModel):
    synced_count: int
    school_partition: dict[str, int]


class AdConnectionTestOut(BaseModel):
    ok: bool
    detail: str
