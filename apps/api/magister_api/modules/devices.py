"""Devices module — device inventory + assignments (M6 #5)."""

from __future__ import annotations

from magister_api.modules.manifest import ModuleManifest
from magister_api.routers.devices import router as devices_router

DEVICES_MODULE = ModuleManifest(id="devices", routers=(devices_router,))
