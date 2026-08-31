"""Registry of feature modules (M6, ADR-0008).

``create_app`` iterates :func:`enabled_modules` and mounts each module's
routers. Modules are fine-grained fachfunctions over the non-toggleable
``platform`` base (M6 #5); which are *effectively* enabled for a running
instance is decided at request time from the instance profile + per-module
overrides (see :mod:`magister_api.modules.catalog`).
"""

from __future__ import annotations

from collections.abc import Sequence

from magister_api.modules.classes import CLASSES_MODULE
from magister_api.modules.departments import DEPARTMENTS_MODULE
from magister_api.modules.devices import DEVICES_MODULE
from magister_api.modules.imports import IMPORTS_MODULE
from magister_api.modules.letters import LETTERS_MODULE
from magister_api.modules.manifest import ModuleManifest
from magister_api.modules.platform import PLATFORM_MODULE
from magister_api.modules.reports import REPORTS_MODULE

# Registration order. Modules use distinct route prefixes, so the order is
# cosmetic (OpenAPI listing) and does not affect routing behaviour.
ALL_MODULES: tuple[ModuleManifest, ...] = (
    PLATFORM_MODULE,
    CLASSES_MODULE,
    LETTERS_MODULE,
    IMPORTS_MODULE,
    DEPARTMENTS_MODULE,
    REPORTS_MODULE,
    DEVICES_MODULE,
)


# The always-mounted base: it carries auth/session/me, so every container —
# including a per-module split container — needs it to authenticate.
_BASE_MODULE_ID = PLATFORM_MODULE.id


class UnknownModuleError(ValueError):
    """A ``container_modules`` entry names a module that does not exist."""


def enabled_modules(container_modules: Sequence[str] | None = None) -> tuple[ModuleManifest, ...]:
    """Modules whose routers ``create_app`` mounts.

    Two independent axes (ADR-0008 D5):

    - **Deployment / container split.** With ``container_modules`` empty
      (default) this returns *every* module — the single-container monolith.
      Passing a subset (from ``MAGISTER_CONTAINER_MODULES``) mounts only those
      modules plus the always-on ``platform`` base, so the same image can run as
      a dedicated per-module container behind a path-routing reverse proxy.
    - **Runtime enable/disable.** Which mounted modules are *effectively enabled*
      for a request (instance profile + per-module overrides) is decided at
      request time by :func:`magister_api.modules.catalog.effective_enabled_ids`
      and the mount-time guard — orthogonal to what a container mounts.
    """
    if not container_modules:
        return ALL_MODULES
    wanted = {m.strip() for m in container_modules if m.strip()}
    known = {m.id for m in ALL_MODULES}
    unknown = sorted(wanted - known)
    if unknown:
        raise UnknownModuleError(
            f"MAGISTER_CONTAINER_MODULES names unknown module(s): {unknown}; known: {sorted(known)}"
        )
    return tuple(m for m in ALL_MODULES if m.id == _BASE_MODULE_ID or m.id in wanted)


def _top_prefix(path: str) -> str:
    """The first path segment of a router prefix, e.g. ``/a/{b}`` → ``/a``."""
    seg = (path or "").strip("/").split("/", 1)[0]
    return f"/{seg}" if seg else ""


def module_path_prefixes() -> dict[str, tuple[str, ...]]:
    """Top-level URL path prefix(es) each module serves, derived from its routers.

    This is the single source of truth for generating reverse-proxy routing to
    a per-module container (see ``scripts/gen_split.py``) and for asserting the
    feature modules stay on disjoint prefixes so ``/api/<prefix>*`` can be routed
    to exactly one container. ``platform`` is the catch-all default target.
    """
    out: dict[str, tuple[str, ...]] = {}
    for module in ALL_MODULES:
        seen: list[str] = []
        for router in module.routers:
            prefix = _top_prefix(getattr(router, "prefix", "") or "")
            if prefix and prefix not in seen:
                seen.append(prefix)
        out[module.id] = tuple(seen)
    return out
