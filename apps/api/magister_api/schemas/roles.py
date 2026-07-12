"""Schemas for the admin role-assignment endpoints (admin/schulleitung/smi)."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field, model_validator

from magister_api.auth.rbac import ROLE_ASSIGNMENT_ROLES

# Roles a human admin may grant/revoke through the API. ``kl`` is intentionally
# excluded — it is derived from class-teacher assignments, not stored here.
GRANTABLE_ROLES = tuple(sorted(ROLE_ASSIGNMENT_ROLES))


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
    role: str = Field(description="One of: admin, schulleitung, smi")
    school_id: int | None = Field(
        default=None,
        description="Required for schulleitung/smi; must be null for admin (cross-school).",
    )

    @model_validator(mode="after")
    def _check_role_scope(self) -> RoleGrantRequest:
        if self.role not in ROLE_ASSIGNMENT_ROLES:
            raise ValueError(f"role must be one of {sorted(ROLE_ASSIGNMENT_ROLES)}")
        if self.role == "admin" and self.school_id is not None:
            raise ValueError("admin is cross-school; school_id must be null")
        if self.role in ("schulleitung", "smi") and self.school_id is None:
            raise ValueError(f"{self.role} requires a school_id")
        return self


class RoleRevokeRequest(RoleGrantRequest):
    """Same shape as a grant — identifies the exact assignment to revoke."""


__all__ = [
    "GRANTABLE_ROLES",
    "RoleAssignmentOut",
    "RoleGrantRequest",
    "RoleRevokeRequest",
]
