"""Request-time enforcement of the enabled-module set (M6 Phase 3, ADR-0008).

Routers are mounted statically, so a disabled module's routes still exist in the
app. This guard — attached to every *toggleable* module's routers at mount time
in ``create_app`` — rejects requests to a module that is currently disabled
(per the instance profile + per-module overrides). So "off" means the API is
off too, not merely hidden in the navigation.

The non-toggleable ``platform`` base gets no guard and is always reachable.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from fastapi import Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from magister_api.config import Settings, get_settings
from magister_api.db import get_session
from magister_api.modules import catalog
from magister_api.services.app_settings import AppSettingsService


def make_module_guard(module_id: str) -> Callable[..., Awaitable[None]]:
    """Build a FastAPI dependency that 404s when *module_id* is disabled."""

    async def _guard(
        settings: Settings = Depends(get_settings),
        session: AsyncSession = Depends(get_session),
    ) -> None:
        cfg = await AppSettingsService(session, settings).get_module_settings()
        enabled = catalog.effective_enabled_ids(cfg.instance_profile, cfg.module_overrides)
        if module_id not in enabled:
            # 404 (not 403): a disabled module simply does not exist here.
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="module_disabled")

    return _guard
