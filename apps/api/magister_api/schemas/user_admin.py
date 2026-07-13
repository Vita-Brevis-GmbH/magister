"""Schemas for admin single-user create/delete + demo-data purge."""

from __future__ import annotations

from pydantic import BaseModel, Field

from magister_api.schemas.common import Upn


class AdUserCreateRequest(BaseModel):
    given_name: str = Field(min_length=1, max_length=64)
    surname: str = Field(min_length=1, max_length=64)
    sam_account_name: str = Field(min_length=1, max_length=20)
    user_principal_name: Upn
    mail: str | None = Field(default=None, max_length=320)
    ou_key: str = Field(description="teacher | student_zyklus3 | student_other")


class AdUserCreateResponse(BaseModel):
    ad_object_guid: str
    # Shown once so the operator can hand it out; never stored or returned again.
    temp_password: str
    force_change: bool = True


class AdUserDeleteResponse(BaseModel):
    ad_object_guid: str
    ad_disabled: bool


class DemoPurgeResponse(BaseModel):
    found: bool
    schools: int = 0
    classes: int = 0
    users: int = 0


__all__ = [
    "AdUserCreateRequest",
    "AdUserCreateResponse",
    "AdUserDeleteResponse",
    "DemoPurgeResponse",
]
