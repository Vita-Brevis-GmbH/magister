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


__all__ = [
    "DepartmentMembershipCreate",
    "DepartmentMembershipOut",
    "ManagerRoleCreate",
    "ManagerRoleOut",
]
