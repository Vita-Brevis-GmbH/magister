"""Schema for the AD group catalog (read-only, for the group picker)."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class AdGroupOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    ad_object_guid: str
    distinguished_name: str
    cn: str
    sam_account_name: str | None = None
    description: str | None = None


__all__ = ["AdGroupOut"]
