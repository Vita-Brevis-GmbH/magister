"""Schemas for department memberships + manager (Kader) roles."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class DepartmentMembershipCreate(BaseModel):
    ad_object_guid: str = Field(min_length=1, max_length=36)
    valid_from: datetime | None = None
    valid_to: datetime | None = None


class DepartmentMembershipOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    department_id: int
    ad_object_guid: str
    valid_from: datetime
    valid_to: datetime | None
    created_at: datetime
    # Display labels (from ad_user_cache) so the SPA can name the person; only
    # populated on the list endpoints, None on the create response.
    display_name: str | None = None
    given_name: str | None = None
    surname: str | None = None
    upn: str | None = None


class ManagerRoleCreate(BaseModel):
    ad_object_guid: str = Field(min_length=1, max_length=36)
    role: Literal["lead", "deputy"] = "lead"
    valid_from: datetime | None = None
    valid_to: datetime | None = None


class ManagerRoleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    department_id: int
    ad_object_guid: str
    role: str
    valid_from: datetime
    valid_to: datetime | None
    created_at: datetime
    # Display labels (from ad_user_cache); only populated on the list endpoint.
    display_name: str | None = None
    given_name: str | None = None
    surname: str | None = None
    upn: str | None = None


class UserDepartmentOut(BaseModel):
    """A department a given person is an active member of (user-centric view)."""

    membership_id: int
    department_id: int
    name: str
    kuerzel: str | None
    valid_from: datetime


__all__ = [
    "DepartmentMembershipCreate",
    "DepartmentMembershipOut",
    "ManagerRoleCreate",
    "ManagerRoleOut",
    "UserDepartmentOut",
]
