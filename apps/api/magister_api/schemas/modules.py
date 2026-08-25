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


class AdminModulesOut(BaseModel):
    instance_profile: str
    known_profiles: list[str]
    modules: list[AdminModuleOut]


class ModuleSettingsUpdate(BaseModel):
    instance_profile: str | None = None
    module_overrides: dict[str, bool] | None = None
