"""Registry of feature modules (M6, ADR-0008).

``create_app`` iterates :func:`enabled_modules` and mounts each module's
routers. Modules are fine-grained fachfunctions over the non-toggleable
``platform`` base (M6 #5); which are *effectively* enabled for a running
instance is decided at request time from the instance profile + per-module
overrides (see :mod:`magister_api.modules.catalog`).
"""

from __future__ import annotations

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


def enabled_modules() -> tuple[ModuleManifest, ...]:
    """Modules whose routers ``create_app`` mounts.

    Routers are mounted once at startup and cannot be unmounted at runtime, so
    this returns every module: mounting is static. Which modules are
    *effectively enabled* for a running instance (driven by the instance
    profile + per-module overrides in ``app_settings``) is answered at request
    time by :func:`magister_api.modules.catalog.effective_enabled_ids`, which
    gates the nav (``GET /me/modules``) and the request guard. See ADR-0008.
    """
    return ALL_MODULES
