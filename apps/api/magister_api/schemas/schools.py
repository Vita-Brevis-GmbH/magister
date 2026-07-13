"""School request/response schemas."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


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


class SchoolUpdate(SchoolBase):
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


__all__ = ["SchoolCreate", "SchoolOut", "SchoolUpdate"]
