"""Class-teacher (KL) request/response schemas."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from magister_api.models.class_teacher_role import (
    ALLOWED_KL_ROLES,
    KL_ROLE_HAUPT,
)
from magister_api.schemas.common import ObjectGuid


class ClassTeacherCreate(BaseModel):
    ad_object_guid: ObjectGuid
    role: str = Field(default=KL_ROLE_HAUPT)
    valid_from: datetime
    valid_to: datetime | None = None

    @field_validator("role")
    @classmethod
    def _check_role(cls, v: str) -> str:
        if v not in ALLOWED_KL_ROLES:
            raise ValueError(f"role must be one of {sorted(ALLOWED_KL_ROLES)}")
        return v


class ClassTeacherOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    class_id: int
    ad_object_guid: str
    role: str
    valid_from: datetime
    valid_to: datetime | None
    created_at: datetime
    # Enriched from ad_user_cache so the SPA can render a friendly label
    # without making a second /users call (which KL can't access).
    display_name: str | None = None
    given_name: str | None = None
    surname: str | None = None
    upn: str | None = None


class SubstitutionOut(ClassTeacherOut):
    """ClassTeacherOut enriched with cross-class context fields."""

    class_name: str
    school_id: int | None = None


__all__ = ["ClassTeacherCreate", "ClassTeacherOut", "SubstitutionOut"]
