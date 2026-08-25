"""Feature-module catalog — pure policy metadata (M6 Phase 1, ADR-0008).

This module deliberately imports NO routers, so any router (``/me/modules``,
``/admin/modules``) can import it without the registry↔router import cycle. It
answers the questions that are independent of HTTP wiring:

- which feature modules exist and their toggle policy (:data:`MODULE_CATALOG`);
- given the instance profile + explicit per-module overrides, which modules are
  effectively enabled (:func:`effective_enabled_ids`);
- whether a candidate enabled-set violates any ``depends_on`` edge.

The router wiring (which routers each module owns) lives in
:mod:`magister_api.modules.registry`.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

# The soft instance profile: it only seeds default module state + vocabulary,
# it never locks a module (ADR-0008 D4).
KNOWN_PROFILES: tuple[str, ...] = ("school", "company", "neutral")
DEFAULT_PROFILE = "school"


@dataclass(frozen=True)
class ModuleMeta:
    """Policy metadata for one feature module.

    ``toggleable`` False marks the always-on base (``platform``) — it can never
    be disabled. ``default_in_profiles`` lists the profiles in which a
    toggleable module is ON by default (an explicit override always wins).
    ``depends_on`` names modules that must also be enabled.
    """

    id: str
    toggleable: bool = True
    default_in_profiles: tuple[str, ...] = ()
    depends_on: tuple[str, ...] = ()


# Granular feature modules (M6 #5). The domain-neutral base is the single
# non-toggleable ``platform`` module; every fachfunction is an individually
# switchable module. The soft profile only seeds a sensible default set — the
# school profile keeps every school feature on, so existing school instances see
# no change; the company profile turns the school superstructure off and the
# company one on. ``depends_on`` guards hard data couplings (letters render
# class letters → need ``classes``).
MODULE_CATALOG: tuple[ModuleMeta, ...] = (
    ModuleMeta(id="platform", toggleable=False),
    # School superstructure.
    ModuleMeta(id="classes", default_in_profiles=("school",), depends_on=("platform",)),
    ModuleMeta(id="letters", default_in_profiles=("school",), depends_on=("classes",)),
    # Imports serve both editions (students/teachers for school, company_users
    # for company), so the import module is on by default in both profiles.
    ModuleMeta(id="imports", default_in_profiles=("school", "company"), depends_on=("platform",)),
    # Company superstructure.
    ModuleMeta(id="departments", default_in_profiles=("company",), depends_on=("platform",)),
    # Cross-domain fachfunctions (useful for both school and company).
    ModuleMeta(id="reports", default_in_profiles=("school", "company"), depends_on=("platform",)),
    ModuleMeta(id="devices", default_in_profiles=("school", "company"), depends_on=("platform",)),
)


def module_ids() -> tuple[str, ...]:
    return tuple(m.id for m in MODULE_CATALOG)


def get_meta(module_id: str) -> ModuleMeta | None:
    return next((m for m in MODULE_CATALOG if m.id == module_id), None)


def _is_on(meta: ModuleMeta, profile: str, overrides: Mapping[str, bool]) -> bool:
    if not meta.toggleable:
        return True  # platform is always on
    override = overrides.get(meta.id)
    if override is not None:
        return override
    return profile in meta.default_in_profiles


def effective_enabled_ids(profile: str, overrides: Mapping[str, bool]) -> list[str]:
    """Ids of modules enabled for *profile* + explicit *overrides*.

    Non-toggleable modules are always included; for toggleable ones an explicit
    override wins, otherwise the module is on iff *profile* is in its default
    set.
    """
    return [m.id for m in MODULE_CATALOG if _is_on(m, profile, overrides)]


def dependency_violations(enabled: set[str]) -> list[tuple[str, str]]:
    """``(module, missing_dep)`` pairs where an enabled module's dep is off."""
    return [
        (m.id, dep)
        for m in MODULE_CATALOG
        if m.id in enabled
        for dep in m.depends_on
        if dep not in enabled
    ]
