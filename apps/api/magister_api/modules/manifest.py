"""The module manifest — the seam that lets features be grouped and toggled.

Kept intentionally small: M6 Phase 0 is a pure refactor that only needs the
router grouping. Later phases extend the manifest without touching callers:

- Phase 1: nav metadata + per-module enable flags (app_settings).
- Phase 3: audit-action + capability declarations that the module-contract CI
  checks enforce (ADR-0008 D8).
"""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import APIRouter


@dataclass(frozen=True)
class ModuleManifest:
    """One feature area and the routers it owns.

    ``id`` is the stable module identifier (also the app_settings key in
    Phase 1). ``depends_on`` names modules that must be enabled for this one to
    make sense (e.g. ``school`` depends on ``platform``); the dependency graph
    is only advisory in Phase 0 and becomes enforced by the admin toggle UI in
    Phase 1.
    """

    id: str
    routers: tuple[APIRouter, ...]
    depends_on: tuple[str, ...] = ()
