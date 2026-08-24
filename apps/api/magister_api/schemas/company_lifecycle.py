"""Schemas for company on-/offboarding (M6 Phase 2)."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class OnboardRequest(BaseModel):
    ad_object_guid: str = Field(min_length=1, max_length=36)
    department_id: int
    # Optionally make the person a manager (Kader) of the same department.
    role: Literal["lead", "deputy"] | None = None
    valid_from: datetime | None = None


class OnboardResult(BaseModel):
    ad_object_guid: str
    department_id: int
    membership_id: int
    manager_role_id: int | None


class OffboardRequest(BaseModel):
    ad_object_guid: str = Field(min_length=1, max_length=36)


class OffboardResult(BaseModel):
    ad_object_guid: str
    memberships_ended: int
    manager_roles_revoked: int


__all__ = [
    "OffboardRequest",
    "OffboardResult",
    "OnboardRequest",
    "OnboardResult",
]
