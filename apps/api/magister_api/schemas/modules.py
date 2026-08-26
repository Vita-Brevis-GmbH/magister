"""Schemas for the M6 feature-module surface (``GET /me/modules``, ADR-0008)."""

from __future__ import annotations

from pydantic import BaseModel


class ModuleOut(BaseModel):
    id: str
    depends_on: list[str]


class ModulesOut(BaseModel):
    profile: str
    modules: list[ModuleOut]


class AdminModuleOut(BaseModel):
    id: str
    toggleable: bool
    enabled: bool
    depends_on: list[str]
    # Profiles in which this module is ON by default. Lets the admin UI compute
    # a "what changes if I switch to profile X" preview before committing.
    default_in_profiles: list[str]


class AdminModulesOut(BaseModel):
    instance_profile: str
    known_profiles: list[str]
    modules: list[AdminModuleOut]
    # Raw per-module overrides (override wins over the profile default). Exposed
    # so the switch-confirmation preview resolves target-enabled the same way the
    # backend does: overrides[id] if set, else (target profile in default_in_profiles).
    module_overrides: dict[str, bool]


class ModuleSettingsUpdate(BaseModel):
    instance_profile: str | None = None
    module_overrides: dict[str, bool] | None = None
