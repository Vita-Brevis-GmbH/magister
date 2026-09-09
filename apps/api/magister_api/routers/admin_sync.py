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
from magister_api.tenancy.context import tenant_from_request

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ad", tags=["ad"])


def get_ad_client(
    request: Request,
    eff: Settings = Depends(get_effective_settings),
) -> AdClient:
    """AD client built from the effective (DB-overlaid) settings.

    Cached per-request per app.state, mirroring ``get_oidc_client``: the
    overlay dep returns the same Settings instance until app_settings.version
    bumps, so this small identity-keyed cache is enough.

    Three backends behind one interface, in this order of precedence:

    1. ``MAGISTER_AD_RPC_URL`` set → ``AdRpcClient``. The strict AD boundary of
       ADR-0011: this process holds no directory credentials and forwards to
       the AD container in the same network.
    2. ``MAGISTER_AD_CONNECTOR_ENABLED`` and a tenant with a console id →
       ``AdConnectorClient``. The hosted case (ADR-0014): the platform never
       opens a connection into the customer's network, the agent calls out.
    3. Otherwise ``AdClient``, talking to AD directly.

    No caller in the domain code knows the difference — that is the whole point
    of the third backend. The cache is per-request per app.state, keyed on the
    identity of the overlaid settings, and now also on the tenant: two tenants
    in one process must not share a client that carries the other's console id.
    """
    base: Settings = request.app.state.settings
    tenant = tenant_from_request(request)
    cache_key = (id(eff), tenant.slug)
    cached: tuple[tuple[int, str], AdClient] | None = getattr(
        request.app.state, "_ad_client_cache", None
    )
    if cached is not None and cached[0] == cache_key:
        return cached[1]
    client: AdClient
    if base.ad_rpc_url and base.ad_rpc_secret is not None:
        # Imported lazily so the direct-AD path carries no httpx-client import.
        from magister_api.ad.rpc_client import AdRpcClient

        client = AdRpcClient(
            eff, base_url=base.ad_rpc_url, secret=base.ad_rpc_secret.get_secret_value()
        )
    elif base.ad_connector_enabled and base.console_registry_url and tenant.console_id:
        from magister_api.ad.connector_client import AdConnectorClient

        client = AdConnectorClient(
            eff,
            console_url=_console_base(base.console_registry_url),
            token=base.console_registry_token.get_secret_value(),
            tenant_id=tenant.console_id,
            management_marker=base.console_management_marker.get_secret_value(),
        )
    else:
        client = AdClient(eff)
    request.app.state._ad_client_cache = (cache_key, client)
    return client


def _console_base(registry_url: str) -> str:
    """Basis-URL der Konsole aus der Registry-URL ableiten.

    Eine Einstellung weniger, die auseinanderlaufen kann: die Registry-URL
    steht ohnehin schon da, und beide Pfade liegen auf derselben Konsole.
    """
    marker = "/api/tenants/registry"
    if registry_url.endswith(marker):
        return registry_url[: -len(marker)]
    return registry_url.rstrip("/")


@router.post("/sync", response_model=AdSyncResultOut, status_code=status.HTTP_200_OK)
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
        device_count=result.devices_imported,
        group_count=result.group_count,
    )


@router.post("/test", response_model=AdConnectionTestOut, status_code=status.HTTP_200_OK)
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
