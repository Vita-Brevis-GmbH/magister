"""Class-membership request/response schemas."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict

from magister_api.schemas.common import ObjectGuid


class ClassMembershipCreate(BaseModel):
    """Add a student to a class.

    Mid-year: if the student already has an active membership in another class,
    the service ends that one (sets ``valid_to``) and opens this one. Adding to
    the same class with overlapping windows is rejected.
    """

    ad_object_guid: ObjectGuid
    valid_from: datetime | None = None
    """Defaults to ``now`` when omitted."""

    valid_to: datetime | None = None


class ClassMembershipOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    class_id: int
    ad_object_guid: str
    valid_from: datetime
    valid_to: datetime | None
    created_at: datetime


__all__ = ["ClassMembershipCreate", "ClassMembershipOut"]
