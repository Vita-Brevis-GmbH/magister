"""Platform module — the domain-neutral gateway base (M6, ADR-0008).

The always-mounted authentication/session core every container needs: OIDC + AD
login, self-service (`/me`), the school scope entity, audit and privacy (DSG).
Identity administration is split out into finer always-on base modules — ``ad``
(AD I/O + sync), ``users`` (accounts + password reset), ``settings`` (config) —
and ``templates`` (Vorlagen); the switchable fachfunctions (classes,
departments, imports, reports, devices) sit on top.
"""

from __future__ import annotations

from magister_api.modules.manifest import ModuleManifest
from magister_api.routers.audit import router as audit_router
from magister_api.routers.auth import router as auth_router
from magister_api.routers.me import router as me_router
from magister_api.routers.privacy import router as privacy_router
from magister_api.routers.schools import router as schools_router

PLATFORM_MODULE = ModuleManifest(
    id="platform",
    routers=(
        auth_router,
        schools_router,
        me_router,
        audit_router,
        privacy_router,
    ),
)
