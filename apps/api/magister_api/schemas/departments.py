"""Department request/response schemas (company edition)."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class DepartmentCreate(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    kuerzel: str | None = Field(default=None, max_length=32)
    details: str | None = Field(default=None, max_length=2000)
    # None = global (standortübergreifend). Admin may create global departments;
    # a unit admin (Schulleitung) always creates within their own Standort.
    school_id: int | None = Field(
        default=None,
        description="Standort id, or None for a global (unbound) department.",
    )
    # AD groups applied to members while their membership is active.
    ad_groups: list[str] = Field(default_factory=list)


class DepartmentUpdate(BaseModel):
    """Patch payload — supply only the fields you want to change."""

    name: str | None = Field(default=None, min_length=1, max_length=64)
    kuerzel: str | None = Field(default=None, max_length=32)
    details: str | None = Field(default=None, max_length=2000)
    ad_groups: list[str] | None = None


class DepartmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    school_id: int | None
    name: str
    kuerzel: str | None
    details: str | None
    ad_groups: list[str] = Field(default_factory=list)
    status: str
    created_at: datetime
    updated_at: datetime
    # Number of currently-active memberships; 0 unless the endpoint fills it in.
    member_count: int = 0


__all__ = ["DepartmentCreate", "DepartmentOut", "DepartmentUpdate"]
