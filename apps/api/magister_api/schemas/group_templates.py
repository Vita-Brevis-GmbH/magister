"""Zielgruppe (``group_templates``) request/response schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

PasswordProfile = Literal["readable", "teacher", "complex"]


class GroupTemplateCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    description: str | None = Field(default=None, max_length=2000)
    kind: str | None = Field(default=None, max_length=32)
    ad_groups: list[str] = Field(default_factory=list)
    # Standorte the template is offered at; empty = global (every Standort).
    school_ids: list[int] = Field(default_factory=list)
    password_profile: PasswordProfile = "complex"  # noqa: S105 — Passwortart, kein Passwort
    force_change: bool = True
    cannot_change_password: bool = False
    password_never_expires: bool = False
    store_password: bool = False


class GroupTemplateUpdate(BaseModel):
    """Patch payload — supply only the fields you want to change."""

    name: str | None = Field(default=None, min_length=1, max_length=80)
    description: str | None = Field(default=None, max_length=2000)
    kind: str | None = Field(default=None, max_length=32)
    ad_groups: list[str] | None = None
    school_ids: list[int] | None = None
    password_profile: PasswordProfile | None = None
    force_change: bool | None = None
    cannot_change_password: bool | None = None
    password_never_expires: bool | None = None
    store_password: bool | None = None


class GroupTemplateOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    description: str | None
    kind: str | None
    ad_groups: list[str] = Field(default_factory=list)
    school_ids: list[int] = Field(default_factory=list)
    status: str
    password_profile: str
    force_change: bool
    cannot_change_password: bool
    password_never_expires: bool
    store_password: bool
    created_at: datetime
    updated_at: datetime


class DefaultsRequest(BaseModel):
    school_id: int


__all__ = [
    "DefaultsRequest",
    "GroupTemplateCreate",
    "GroupTemplateOut",
    "GroupTemplateUpdate",
    "PasswordProfile",
]
