"""Admin-triggered AD sync. The periodic scheduler is a follow-up — for M1 we
keep the manual ``POST /admin/ad-sync`` endpoint and drive it from a cron sidecar
or a future lifespan task.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from magister_api.ad.client import AdClient
from magister_api.ad.errors import AdUnavailableError
from magister_api.auth.current_user import AuthenticatedUser
from magister_api.auth.effective_settings import get_effective_settings
from magister_api.auth.rbac import require_admin
from magister_api.config import Settings
from magister_api.db import get_session
from magister_api.schemas.ad_users import AdSyncResultOut
from magister_api.services.ad_sync import AdSyncService

router = APIRouter(prefix="/admin", tags=["admin"])


def get_ad_client(
    request: Request,
    eff: Settings = Depends(get_effective_settings),
) -> AdClient:
    """AD client built from the effective (DB-overlaid) settings.

    Cached per-request per app.state, mirroring ``get_oidc_client``: the
    overlay dep returns the same Settings instance until app_settings.version
    bumps, so this small identity-keyed cache is enough.
    """
    cached: tuple[int, AdClient] | None = getattr(request.app.state, "_ad_client_cache", None)
    if cached is not None and cached[0] == id(eff):
        return cached[1]
    client = AdClient(eff)
    request.app.state._ad_client_cache = (id(eff), client)
    return client


@router.post("/ad-sync", response_model=AdSyncResultOut, status_code=status.HTTP_200_OK)
async def trigger_ad_sync(
    request: Request,
    user: AuthenticatedUser = Depends(require_admin),
    settings: Settings = Depends(get_effective_settings),
    session: AsyncSession = Depends(get_session),
    ad: AdClient = Depends(get_ad_client),
) -> AdSyncResultOut:
    svc = AdSyncService(session, settings, ad)
    request_id = getattr(request.state, "request_id", "")
    client_ip = getattr(request.state, "client_ip", None)
    try:
        result = await svc.sync_all(
            actor_upn=user.upn,
            actor_object_guid=user.ad_object_guid,
            ip=client_ip,
            request_id=request_id,
        )
    except AdUnavailableError as exc:
        raise HTTPException(status_code=503, detail="ad_unavailable") from exc
    return AdSyncResultOut(
        synced_count=result.synced_count,
        school_partition={str(k): v for k, v in result.school_partition.items()},
    )


__all__ = ["router", "get_ad_client"]
