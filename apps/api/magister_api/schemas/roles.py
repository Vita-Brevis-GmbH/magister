"""Schemas for the admin role-assignment endpoints (admin/schulleitung/smi)."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class RoleAssignmentOut(BaseModel):
    ad_object_guid: str
    role: str
    school_id: int | None
    school_name: str | None
    granted_by: str | None
    granted_at: datetime
    # Display labels (from ad_user_cache) so the UI can name the holder.
    display_name: str | None = None
    given_name: str | None = None
    surname: str | None = None
    upn: str | None = None


class RoleGrantRequest(BaseModel):
    """A role grant. The role must exist (built-in or custom, ADR-0010); the
    admin super-role is cross-school (``school_id`` null) and every other role
    is scoped to exactly one org unit. Those role-flag-dependent rules are
    enforced in the router against the DB role definition, not here."""

    role: str = Field(min_length=1, max_length=32)
    school_id: int | None = Field(
        default=None,
        description="Required for every non-admin role; must be null for admin (cross-school).",
    )


class RoleRevokeRequest(RoleGrantRequest):
    """Same shape as a grant — identifies the exact assignment to revoke."""


__all__ = [
    "RoleAssignmentOut",
    "RoleGrantRequest",
    "RoleRevokeRequest",
]
