"""School request/response schemas."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class SchoolAdConfig(BaseModel):
    """Per-school AD provisioning config (target OUs + Zyklus group templates)."""

    ad_ou_students_zyklus3: str | None = Field(default=None, max_length=512)
    ad_ou_students_other: str | None = Field(default=None, max_length=512)
    ad_ou_teachers: str | None = Field(default=None, max_length=512)
    ad_ou_devices: str | None = Field(default=None, max_length=512)
    ad_groups_teacher: list[str] | None = None
    ad_groups_student_zyklus1: list[str] | None = None
    ad_groups_student_zyklus2: list[str] | None = None
    ad_groups_student_zyklus3: list[str] | None = None


class SchoolBase(BaseModel):
    street: str | None = Field(default=None, max_length=200)
    postal_code: str | None = Field(default=None, max_length=20)
    city: str | None = Field(default=None, max_length=120)
    phone: str | None = Field(default=None, max_length=50)
    description: str | None = Field(default=None, max_length=4000)
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)


class SchoolCreate(SchoolBase):
    name: str = Field(min_length=1, max_length=200)
    kuerzel: str = Field(min_length=1, max_length=50)
    scope_short: str = Field(min_length=1, max_length=50)


class SchoolUpdate(SchoolBase, SchoolAdConfig):
    """Patch payload — supply only the fields you want to change."""

    name: str | None = Field(default=None, min_length=1, max_length=200)
    kuerzel: str | None = Field(default=None, min_length=1, max_length=50)
    scope_short: str | None = Field(default=None, min_length=1, max_length=50)


class SchoolOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    kuerzel: str
    scope_short: str
    street: str | None = None
    postal_code: str | None = None
    city: str | None = None
    phone: str | None = None
    description: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    # Per-school AD provisioning config.
    ad_ou_students_zyklus3: str | None = None
    ad_ou_students_other: str | None = None
    ad_ou_teachers: str | None = None
    ad_ou_devices: str | None = None
    ad_groups_teacher: list[str] = Field(default_factory=list)
    ad_groups_student_zyklus1: list[str] = Field(default_factory=list)
    ad_groups_student_zyklus2: list[str] = Field(default_factory=list)
    ad_groups_student_zyklus3: list[str] = Field(default_factory=list)


__all__ = ["SchoolAdConfig", "SchoolCreate", "SchoolOut", "SchoolUpdate"]
