"""Schemas for the teacher-facing "my students" view (KL + Fachlehrer)."""

from __future__ import annotations

from pydantic import BaseModel


class MyStudentBrief(BaseModel):
    ad_object_guid: str
    display_name: str | None
    upn: str | None


class MyClassStudents(BaseModel):
    class_id: int
    name: str
    kuerzel: str | None
    students: list[MyStudentBrief]


class MyStudentsOut(BaseModel):
    classes: list[MyClassStudents]


__all__ = ["MyClassStudents", "MyStudentBrief", "MyStudentsOut"]
