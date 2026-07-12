"""Auth-related request/response schemas."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from magister_api.schemas.common import ObjectGuid, Upn


class AdLoginRequest(BaseModel):
    """Direct AD-credential login (username + password over LDAPS)."""

    login: str = Field(min_length=1, max_length=256, description="sAMAccountName or UPN")
    password: str = Field(min_length=1, max_length=512)


class CurrentUserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    ad_object_guid: ObjectGuid
    upn: Upn
    given_name: str | None = None
    surname: str | None = None
    display_name: str | None = None
    is_admin: bool
    school_scope: list[int] = Field(
        default_factory=list,
        description="School IDs the user has Schulleitung-or-above scope on. Empty for KL-only.",
    )
    roles: list[str] = Field(default_factory=list)
    expires_at: datetime
