"""User-configuration settings — the subset of ``app_settings`` that the
Schulträger-IT / Schulleitung (not just the system admin) maintain.

Holds the provisioning target OUs, the Zyklus boundaries, the password-vault
master switch, the group-catalog search base, and the default AD group
templates per category. Deliberately excludes OIDC / AD-connection / secret
fields — those stay on the admin-only system-settings surface.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class AdUserSettingsOut(BaseModel):
    version: int
    ad_ou_students_zyklus3: str | None
    ad_ou_students_other: str | None
    ad_ou_teachers: str | None
    zyklus1_max_grade: int
    zyklus2_max_grade: int
    password_store_enabled: bool
    ad_groups_search_base: str | None
    ad_groups_teacher: list[str]
    ad_groups_student_zyklus1: list[str]
    ad_groups_student_zyklus2: list[str]
    ad_groups_student_zyklus3: list[str]


class AdUserSettingsUpdate(BaseModel):
    """All fields optional — ``None`` means "leave unchanged"."""

    ad_ou_students_zyklus3: str | None = None
    ad_ou_students_other: str | None = None
    ad_ou_teachers: str | None = None
    zyklus1_max_grade: int | None = Field(default=None, ge=1, le=13)
    zyklus2_max_grade: int | None = Field(default=None, ge=1, le=13)
    password_store_enabled: bool | None = None
    ad_groups_search_base: str | None = None
    ad_groups_teacher: list[str] | None = None
    ad_groups_student_zyklus1: list[str] | None = None
    ad_groups_student_zyklus2: list[str] | None = None
    ad_groups_student_zyklus3: list[str] | None = None


__all__ = ["AdUserSettingsOut", "AdUserSettingsUpdate"]
