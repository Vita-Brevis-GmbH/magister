"""Schemas for the M6 feature-module surface (``GET /me/modules``, ADR-0008)."""

from __future__ import annotations

from pydantic import BaseModel


class ModuleOut(BaseModel):
    id: str
    depends_on: list[str]


class ModulesOut(BaseModel):
    modules: list[ModuleOut]
