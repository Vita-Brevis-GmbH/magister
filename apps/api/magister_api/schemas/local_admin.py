"""Pydantic schemas for the local-admin login + admin lifecycle endpoints."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class LocalLoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=512)


class LocalAdminOut(BaseModel):
    """Status surface for the GUI. Never returns the hash."""

    model_config = ConfigDict(from_attributes=True)

    username: str
    enabled: bool
    locked_until: datetime | None
    last_login_at: datetime | None
    password_changed_at: datetime


class LocalAdminPasswordChangeRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=512)
    new_password: str = Field(min_length=12, max_length=512)


class LocalAdminEnabledUpdate(BaseModel):
    enabled: bool


__all__ = [
    "LocalAdminEnabledUpdate",
    "LocalAdminOut",
    "LocalAdminPasswordChangeRequest",
    "LocalLoginRequest",
]
