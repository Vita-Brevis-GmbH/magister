"""AD group template ("Zielrolle") request/response schemas."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class GroupTemplateCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    description: str | None = Field(default=None, max_length=2000)
    kind: str | None = Field(default=None, max_length=32)
    ad_groups: list[str] = Field(default_factory=list)
    # Standorte the template is offered at; empty = global (every Standort).
    school_ids: list[int] = Field(default_factory=list)


class GroupTemplateUpdate(BaseModel):
    """Patch payload — supply only the fields you want to change."""

    name: str | None = Field(default=None, min_length=1, max_length=80)
    description: str | None = Field(default=None, max_length=2000)
    kind: str | None = Field(default=None, max_length=32)
    ad_groups: list[str] | None = None
    school_ids: list[int] | None = None


class GroupTemplateOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    description: str | None
    kind: str | None
    ad_groups: list[str] = Field(default_factory=list)
    school_ids: list[int] = Field(default_factory=list)
    status: str
    created_at: datetime
    updated_at: datetime


__all__ = ["GroupTemplateCreate", "GroupTemplateOut", "GroupTemplateUpdate"]
