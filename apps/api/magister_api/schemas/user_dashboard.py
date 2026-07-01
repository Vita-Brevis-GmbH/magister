"""Read-only aggregate for the per-user dashboard.

Surfaces the classes a user is an active member of, plus the active
class-teachers (KL) of each of those classes, so the user-detail view can
show "class + Klassenlehrer" without the SPA stitching several calls.
"""

from __future__ import annotations

from pydantic import BaseModel


class ClassTeacherBrief(BaseModel):
    ad_object_guid: str
    display_name: str | None
    upn: str | None
    role: str


class UserClassOut(BaseModel):
    class_id: int
    name: str
    kuerzel: str | None
    jahrgangsstufe: int
    teachers: list[ClassTeacherBrief]


class UserDashboardOut(BaseModel):
    classes: list[UserClassOut]


__all__ = ["ClassTeacherBrief", "UserClassOut", "UserDashboardOut"]
