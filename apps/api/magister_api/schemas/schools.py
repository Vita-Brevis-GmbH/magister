"""School response schemas."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class SchoolOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    kuerzel: str
    scope_short: str


__all__ = ["SchoolOut"]
