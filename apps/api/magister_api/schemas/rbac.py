"""Schemas for the dynamic-roles admin surface (`/admin/rbac`, ADR-0010)."""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator

from magister_api.auth.capabilities import Capability


class RoleOut(BaseModel):
    key: str
    name: str
    is_system: bool
    is_admin: bool
    is_derived: bool
    # UI affordances derived from the flags above (server is authoritative).
    editable: bool  # capability set may be changed
    renamable: bool
    deletable: bool
    capabilities: list[str]


class RbacConfigOut(BaseModel):
    # The full capability vocabulary (code-defined) so the matrix can render a
    # column per capability, independent of what any role currently holds.
    capabilities: list[str]
    roles: list[RoleOut]


class RoleCreate(BaseModel):
    key: str = Field(min_length=2, max_length=32, pattern=r"^[a-z][a-z0-9_-]*$")
    name: str = Field(min_length=1, max_length=64)


class RoleRename(BaseModel):
    name: str = Field(min_length=1, max_length=64)


class RoleCapabilitiesUpdate(BaseModel):
    capabilities: list[str]

    @field_validator("capabilities")
    @classmethod
    def _known_caps(cls, v: list[str]) -> list[str]:
        valid = {c.value for c in Capability}
        unknown = [c for c in v if c not in valid]
        if unknown:
            raise ValueError(f"unknown capabilities: {sorted(unknown)}")
        return v


__all__ = [
    "RbacConfigOut",
    "RoleCapabilitiesUpdate",
    "RoleCreate",
    "RoleOut",
    "RoleRename",
]
