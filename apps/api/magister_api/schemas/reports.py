"""Response schemas for the read-only reporting endpoints (M3 US-3)."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class StudentsByClassRow(BaseModel):
    class_id: int
    school_id: int
    name: str
    kuerzel: str | None
    jahrgangsstufe: int
    student_count: int


class StudentsByClassReport(BaseModel):
    rows: list[StudentsByClassRow]
    total_students: int
    total_classes: int


class TeacherWorkloadRow(BaseModel):
    ad_object_guid: str
    upn: str | None
    display_name: str | None
    haupt_count: int
    co_count: int
    stellvertretung_count: int
    total: int


class TeacherWorkloadReport(BaseModel):
    rows: list[TeacherWorkloadRow]


class ActivityRow(BaseModel):
    action: str
    count: int


class ActivityReport(BaseModel):
    since: datetime
    rows: list[ActivityRow]


__all__ = [
    "ActivityReport",
    "ActivityRow",
    "StudentsByClassReport",
    "StudentsByClassRow",
    "TeacherWorkloadReport",
    "TeacherWorkloadRow",
]
