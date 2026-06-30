"""Class request/response schemas."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from magister_api.models.school_class import (
    CLASS_STATUS_ACTIVE,
    CLASS_STATUS_ARCHIVED,
)


class ClassCreate(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    kuerzel: str | None = Field(default=None, max_length=32)
    jahrgangsstufe: int = Field(ge=1, le=13)
    details: str | None = Field(default=None, max_length=2000)
    school_id: int = Field(
        description="Schulträger-Admin must set this; Schulleitung gets it derived from scope.",
        default=0,
    )


class ClassUpdate(BaseModel):
    """Patch payload — supply only the fields you want to change."""

    name: str | None = Field(default=None, min_length=1, max_length=64)
    kuerzel: str | None = Field(default=None, max_length=32)
    details: str | None = Field(default=None, max_length=2000)


class ClassOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    school_id: int
    name: str
    kuerzel: str | None
    jahrgangsstufe: int
    details: str | None
    status: str
    created_at: datetime
    updated_at: datetime


class ClassPromotionRequest(BaseModel):
    """Promote active students from this class to a target class.

    ``student_guids`` selects a subset; omit (null) to move all active students.
    """

    target_class_id: int
    archive_source: bool = False
    student_guids: list[str] | None = None


class ClassPromotionError(BaseModel):
    ad_object_guid: str
    detail: str


class ClassPromotionResult(BaseModel):
    students_moved: int
    students_failed: int
    errors: list[ClassPromotionError]
    source_archived: bool


__all__ = [
    "CLASS_STATUS_ACTIVE",
    "CLASS_STATUS_ARCHIVED",
    "ClassCreate",
    "ClassOut",
    "ClassPromotionError",
    "ClassPromotionRequest",
    "ClassPromotionResult",
    "ClassUpdate",
]
