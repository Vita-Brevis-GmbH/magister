"""Imports module — CSV stage/diff/apply provisioning (M6 #5)."""

from __future__ import annotations

from magister_api.modules.manifest import ModuleManifest
from magister_api.routers.imports import router as imports_router

IMPORTS_MODULE = ModuleManifest(id="imports", routers=(imports_router,))
