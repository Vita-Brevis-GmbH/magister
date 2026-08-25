"""Department request/response schemas (company edition)."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class DepartmentCreate(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    kuerzel: str | None = Field(default=None, max_length=32)
    details: str | None = Field(default=None, max_length=2000)
    school_id: int = Field(
        default=0,
        description="Admin must set this; Schulleitung/unit-admin derives it from scope.",
    )


class DepartmentUpdate(BaseModel):
    """Patch payload — supply only the fields you want to change."""

    name: str | None = Field(default=None, min_length=1, max_length=64)
    kuerzel: str | None = Field(default=None, max_length=32)
    details: str | None = Field(default=None, max_length=2000)


class DepartmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    school_id: int
    name: str
    kuerzel: str | None
    details: str | None
    status: str
    created_at: datetime
    updated_at: datetime


__all__ = ["DepartmentCreate", "DepartmentOut", "DepartmentUpdate"]
