"""Device request/response schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

# Assignment targets exposed to the API. ``free`` clears any assignment.
AssignmentType = Literal["person", "class", "school", "free"]


class DeviceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    device_type: str | None = Field(default=None, max_length=64)
    serial_number: str | None = Field(default=None, max_length=128)
    notes: str | None = Field(default=None, max_length=4000)


class DeviceUpdate(BaseModel):
    """Patch payload — supply only the fields you want to change."""

    name: str | None = Field(default=None, min_length=1, max_length=255)
    device_type: str | None = Field(default=None, max_length=64)
    serial_number: str | None = Field(default=None, max_length=128)
    notes: str | None = Field(default=None, max_length=4000)


class DeviceAssign(BaseModel):
    """Bind (or unbind) a device.

    - ``person`` → ``person_guid`` required.
    - ``class``  → ``class_id`` required.
    - ``school`` → ``school_id`` required.
    - ``free``   → no target; clears the assignment.
    """

    assignment_type: AssignmentType
    person_guid: str | None = None
    class_id: int | None = None
    school_id: int | None = None


class DeviceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    device_type: str | None
    serial_number: str | None
    notes: str | None
    school_id: int | None
    class_id: int | None
    assigned_person_guid: str | None
    ad_object_guid: str | None
    source: str
    created_at: datetime
    updated_at: datetime


__all__ = [
    "AssignmentType",
    "DeviceAssign",
    "DeviceCreate",
    "DeviceOut",
    "DeviceUpdate",
]
