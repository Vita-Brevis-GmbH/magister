"""Subject-teacher (Fachlehrer) request/response schemas."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from magister_api.schemas.common import ObjectGuid


class SubjectTeacherCreate(BaseModel):
    ad_object_guid: ObjectGuid
    subject: str = Field(min_length=1, max_length=100)
    valid_from: datetime
    valid_to: datetime | None = None


class SubjectTeacherOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    class_id: int
    ad_object_guid: str
    subject: str
    valid_from: datetime
    valid_to: datetime | None
    created_at: datetime
    display_name: str | None = None
    given_name: str | None = None
    surname: str | None = None
    upn: str | None = None


__all__ = ["SubjectTeacherCreate", "SubjectTeacherOut"]
