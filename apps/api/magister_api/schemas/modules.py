"""Schemas for the M6 feature-module surface (``GET /me/modules``, ADR-0008)."""

from __future__ import annotations

from pydantic import BaseModel


class ModuleOut(BaseModel):
    id: str
    depends_on: list[str]


class ModulesOut(BaseModel):
    profile: str
    modules: list[ModuleOut]
    #: Ob diese Installation von einer Konsole verwaltet wird (ADR-0017 D1).
    #:
    #: Steht hier und nicht in einem eigenen Endpunkt, weil das Frontend diese
    #: Antwort schon für die Navigation liest: es blendet Menüpunkte nach den
    #: Modul-Ids aus. „Systemeinstellungen" und „Rechte" sind derselbe Fall —
    #: nur ist der Grund kein abgeschaltetes Modul, sondern ein Betreiber.
    #:
    #: Vorgabe `False`, damit ein älteres Frontend gegen eine neuere API
    #: dasselbe tut wie bisher.
    platform_managed: bool = False


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
