"""Pydantic schemas for the local-admin login + admin lifecycle endpoints."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class LocalLoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=512)


class LocalLoginStageOut(BaseModel):
    """What the SPA must do next after the password checked out.

    ``stage`` is ``"totp"`` (ask for a code) or ``"enroll"`` (force enrolment).
    The enrolment fields are set only in the ``enroll`` stage.
    """

    stage: str
    challenge: str
    provisioning_uri: str | None = None
    qr_data_uri: str | None = None
    secret: str | None = None


class LocalTotpRequest(BaseModel):
    challenge: str = Field(min_length=1, max_length=2048)
    code: str = Field(min_length=1, max_length=32)


class LocalEnrollConfirmOut(BaseModel):
    """The recovery codes, shown exactly once."""

    recovery_codes: list[str]


class LocalAdminMfaOut(BaseModel):
    """MFA status for the admin surface. Never returns a secret or a code."""

    enrolled: bool
    recovery_codes_left: int
    reset_at: datetime | None
    reset_by: str | None
    suspended_until: datetime | None


class LocalAdminMfaSuspendRequest(BaseModel):
    reason: str = Field(min_length=3, max_length=200, description="Grund oder Ticketnummer")


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
    "LocalAdminMfaOut",
    "LocalAdminMfaSuspendRequest",
    "LocalAdminOut",
    "LocalAdminPasswordChangeRequest",
    "LocalEnrollConfirmOut",
    "LocalLoginRequest",
    "LocalLoginStageOut",
    "LocalTotpRequest",
]
