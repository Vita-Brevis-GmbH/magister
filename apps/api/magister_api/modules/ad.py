"""AD module — the single owner of Active-Directory I/O (M6, ADR-0008).

The one place that reads from and writes to AD: the recurring sync (read loop,
started from the app lifespan and gated to exactly one container via
``MAGISTER_RUN_SCHEDULER``), the manual sync/connection-probe endpoints, the
synced group catalog, and single-account create/delete. Everything AD-facing
lives under the ``/ad`` prefix so it routes to exactly one container; other
modules that need AD reach it here (in the monolith in-process, in the strict
split via the internal AD API).
"""

from __future__ import annotations

from magister_api.modules.manifest import ModuleManifest
from magister_api.routers.admin_ad_groups import router as admin_ad_groups_router
from magister_api.routers.admin_sync import router as admin_sync_router
from magister_api.routers.admin_users import router as admin_users_router

AD_MODULE = ModuleManifest(
    id="ad",
    routers=(
        admin_sync_router,
        admin_ad_groups_router,
        admin_users_router,
    ),
)
