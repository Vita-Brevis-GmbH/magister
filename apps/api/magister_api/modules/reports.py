"""Reports module — analytics/exports (M6 #5). Useful for school and company."""

from __future__ import annotations

from magister_api.modules.manifest import ModuleManifest
from magister_api.routers.reports import router as reports_router

REPORTS_MODULE = ModuleManifest(id="reports", routers=(reports_router,))
