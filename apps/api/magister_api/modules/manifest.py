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

    ``id`` is the stable module identifier — the same id used in
    :mod:`magister_api.modules.catalog`, which carries the *policy* metadata
    (toggle flag, profile defaults, dependencies). The manifest carries only
    the HTTP wiring (its routers), so it can import the routers without the
    catalog having to — that keeps the catalog import-cycle-free.
    """

    id: str
    routers: tuple[APIRouter, ...]
