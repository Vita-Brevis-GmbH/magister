"""Class request/response schemas."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator

from magister_api.models.school_class import (
    CLASS_STATUS_ACTIVE,
    CLASS_STATUS_ARCHIVED,
)

# Grade bounds: -1 = 1. Kindergarten, 0 = 2. Kindergarten, 1..13 = Klassen.
GRADE_MIN = -1
GRADE_MAX = 13


class ClassCreate(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    kuerzel: str | None = Field(default=None, max_length=32)
    # Lower/primary grade (drives Zyklus/OU routing, sorting, promotion).
    jahrgangsstufe: int = Field(ge=GRADE_MIN, le=GRADE_MAX)
    # Upper grade for multi-grade classes; omit/null for a single grade.
    jahrgangsstufe_bis: int | None = Field(default=None, ge=GRADE_MIN, le=GRADE_MAX)
    details: str | None = Field(default=None, max_length=2000)
    school_id: int = Field(
        description="Schulträger-Admin must set this; Schulleitung gets it derived from scope.",
        default=0,
    )

    @model_validator(mode="after")
    def _check_range(self) -> ClassCreate:
        if self.jahrgangsstufe_bis is not None and self.jahrgangsstufe_bis < self.jahrgangsstufe:
            raise ValueError("jahrgangsstufe_bis must be >= jahrgangsstufe")
        return self


class ClassUpdate(BaseModel):
    """Patch payload — supply only the fields you want to change."""

    name: str | None = Field(default=None, min_length=1, max_length=64)
    kuerzel: str | None = Field(default=None, max_length=32)
    jahrgangsstufe: int | None = Field(default=None, ge=GRADE_MIN, le=GRADE_MAX)
    # Send an explicit null to clear the upper bound (make it single-grade).
    jahrgangsstufe_bis: int | None = Field(default=None, ge=GRADE_MIN, le=GRADE_MAX)
    details: str | None = Field(default=None, max_length=2000)


class ClassOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    school_id: int
    name: str
    kuerzel: str | None
    jahrgangsstufe: int
    jahrgangsstufe_bis: int | None
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
    # Advance each moved student's own grade by +1 (default). Set false to keep
    # grades unchanged. ``grade_overrides`` maps ad_object_guid -> explicit new
    # grade for exceptions (staying / skipping).
    bump_grade: bool = True
    grade_overrides: dict[str, int] | None = None


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
