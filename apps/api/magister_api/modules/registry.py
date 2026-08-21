"""Registry of feature modules (M6 Phase 0, ADR-0008).

``create_app`` iterates :func:`enabled_modules` and mounts each module's
routers, instead of hard-listing 25 ``include_router`` calls.
"""

from __future__ import annotations

from magister_api.modules.manifest import ModuleManifest
from magister_api.modules.platform import PLATFORM_MODULE
from magister_api.modules.school import SCHOOL_MODULE

# Registration order. Modules use distinct route prefixes, so the order is
# cosmetic (OpenAPI listing) and does not affect routing behaviour.
ALL_MODULES: tuple[ModuleManifest, ...] = (PLATFORM_MODULE, SCHOOL_MODULE)


def enabled_modules() -> tuple[ModuleManifest, ...]:
    """Modules whose routers ``create_app`` should mount.

    Phase 0: every registered module is enabled, so the mounted route set is
    identical to the previous hard-coded list. Phase 1 filters this by the
    per-module enable flags in ``app_settings`` (via ``effective_settings``)
    and the selected instance profile — see ADR-0008.
    """
    return ALL_MODULES
