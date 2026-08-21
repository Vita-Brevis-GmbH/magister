"""Registry of feature modules (M6 Phase 0, ADR-0008).

``create_app`` iterates :func:`enabled_modules` and mounts each module's
routers, instead of hard-listing 25 ``include_router`` calls.
"""

from __future__ import annotations

from magister_api.modules.company import COMPANY_MODULE
from magister_api.modules.manifest import ModuleManifest
from magister_api.modules.platform import PLATFORM_MODULE
from magister_api.modules.school import SCHOOL_MODULE

# Registration order. Modules use distinct route prefixes, so the order is
# cosmetic (OpenAPI listing) and does not affect routing behaviour.
ALL_MODULES: tuple[ModuleManifest, ...] = (PLATFORM_MODULE, SCHOOL_MODULE, COMPANY_MODULE)


def enabled_modules() -> tuple[ModuleManifest, ...]:
    """Modules whose routers ``create_app`` mounts.

    Routers are mounted once at startup and cannot be unmounted at runtime, so
    this returns every module: mounting is static. Which modules are
    *effectively enabled* for a running instance (driven by the instance
    profile + per-module overrides in ``app_settings``) is answered at request
    time by :func:`magister_api.modules.catalog.effective_enabled_ids`, which
    gates the nav (``GET /me/modules``) and the admin surface. See ADR-0008.
    """
    return ALL_MODULES
