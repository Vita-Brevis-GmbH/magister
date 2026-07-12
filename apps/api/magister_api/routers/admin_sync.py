"""Admin-triggered AD sync. This is the manual on-demand trigger; the recurring
sync runs in-process via :mod:`magister_api.services.ad_sync_scheduler` (started
from the app lifespan, interval from ``app_settings.ad_sync_interval_minutes``).
"""

from __future__ import annotations

import logging
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from magister_api.ad.client import AdClient
from magister_api.ad.errors import AdUnavailableError, classify_sync_failure
from magister_api.audit.service import AuditService
from magister_api.auth.current_user import AuthenticatedUser
from magister_api.auth.effective_settings import get_effective_settings
from magister_api.auth.rbac import require_admin
from magister_api.config import Settings
from magister_api.db import get_session
from magister_api.schemas.ad_users import AdConnectionTestOut, AdSyncResultOut
from magister_api.services.ad_sync import AdSyncService

logger = logging.getLogger(__name__)

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
    mode: Literal["full", "incremental"] = Query(default="full"),
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
            mode=mode,
        )
    except AdUnavailableError as exc:
        # The bind may be fine (the connection test is green) yet the sync still
        # fails because it searches a subtree — surface the specific reason
        # instead of a misleading "unreachable". Log the category (never creds).
        reason = classify_sync_failure(exc)
        # ``str(exc)`` carries only internal markers + the LDAP result
        # description (e.g. "ldap_search_failed:noSuchObject") — no credentials.
        logger.warning("AD sync failed: reason=%s detail=%s", reason, exc)
        raise HTTPException(status_code=503, detail=reason) from exc
    return AdSyncResultOut(
        synced_count=result.synced_count,
        school_partition={str(k): v for k, v in result.school_partition.items()},
    )


@router.post("/ad-test", response_model=AdConnectionTestOut, status_code=status.HTTP_200_OK)
async def test_ad_connection(
    request: Request,
    user: AuthenticatedUser = Depends(require_admin),
    settings: Settings = Depends(get_effective_settings),
    session: AsyncSession = Depends(get_session),
    ad: AdClient = Depends(get_ad_client),
) -> AdConnectionTestOut:
    """Validate the configured AD service-account bind (read-only probe).

    Never echoes or logs credentials; the audit event records only the boolean
    outcome so operators can see that a test was run.
    """
    ok, reason = await ad.probe_service_connection_detailed()
    audit = AuditService(session, settings)
    await audit.emit(
        action="ad_connection_tested",
        target_kind="ad",
        target_id="service_account",
        actor_upn=user.upn,
        actor_object_guid=user.ad_object_guid,
        school_id=None,
        ip=getattr(request.state, "client_ip", None),
        request_id=getattr(request.state, "request_id", ""),
        payload={"ok": ok, "reason": reason},
    )
    return AdConnectionTestOut(ok=ok, detail=reason)


__all__ = ["router", "get_ad_client"]
