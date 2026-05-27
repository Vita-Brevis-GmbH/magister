"""Periodic AD-sync scheduler — the recurring half of M1's "AD … periodischer
Sync funktional".

The manual :http:post:`/admin/ad-sync` endpoint is complemented by this
in-process background loop. It is started/stopped by the FastAPI lifespan and
driven by ``app_settings.ad_sync_interval_minutes`` (editable from the admin
GUI without a restart — every tick re-reads the effective settings, so an
interval or AD-config change is picked up on the next cycle).

Resilience: a tick that fails (AD unavailable, transient DB error) is logged —
and, for AD-unavailable, audited as ``ad_sync_failed`` — but never kills the
loop. Before AD is configured (first-boot M1.5 flow) ticks are skipped.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import Callable

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from magister_api.ad.client import AdClient
from magister_api.ad.errors import AdUnavailableError
from magister_api.auth.effective_settings import load_effective_settings
from magister_api.config import Settings
from magister_api.services.ad_sync import AdSyncService

logger = logging.getLogger(__name__)

SCHEDULER_ACTOR_UPN = "system:ad-sync-scheduler"


def _ad_configured(settings: Settings) -> bool:
    """True when there is enough config for a sync to even be attempted.

    Both modes need a user search base — without it ``search_users`` raises
    immediately. Live mode additionally needs at least one DC; mock mode (tests)
    does not.
    """
    if not settings.ad_users_search_base:
        return False
    return settings.ad_use_mock or bool(settings.ad_dcs)


async def _run_tick(
    session: AsyncSession,
    settings: Settings,
    client_factory: Callable[[Settings], AdClient],
) -> None:
    ad = client_factory(settings)
    try:
        # request_id column is VARCHAR(36); actor_upn already marks the origin.
        await AdSyncService(session, settings, ad).sync_all(
            actor_upn=SCHEDULER_ACTOR_UPN,
            actor_object_guid=None,
            ip=None,
            request_id=uuid.uuid4().hex,
        )
    finally:
        await ad.aclose()


async def _interruptible_sleep(stop_event: asyncio.Event, seconds: float) -> None:
    """Sleep up to *seconds*, returning early the moment *stop_event* is set."""
    try:
        await asyncio.wait_for(stop_event.wait(), timeout=seconds)
    except TimeoutError:
        pass


async def run_ad_sync_loop(
    base_settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    *,
    stop_event: asyncio.Event,
    client_factory: Callable[[Settings], AdClient] = AdClient,
) -> None:
    """Run scheduled AD syncs until *stop_event* is set.

    Each iteration opens a session, computes the effective (DB-overlaid)
    settings, syncs when AD is configured, then waits
    ``ad_sync_interval_minutes`` — interruptibly, so shutdown is prompt.
    """
    logger.info("AD-sync scheduler started")
    while not stop_event.is_set():
        interval_minutes = max(1, base_settings.ad_sync_interval_minutes)
        try:
            async with session_factory() as session:
                settings = await load_effective_settings(session, base_settings)
                interval_minutes = max(1, settings.ad_sync_interval_minutes)
                if _ad_configured(settings):
                    try:
                        await _run_tick(session, settings, client_factory)
                    except AdUnavailableError as exc:
                        logger.warning("scheduled AD sync: AD unavailable (%s)", exc)
                    # Commit either way: persists ad_sync_completed + cache rows
                    # on success, or the ad_sync_failed audit row otherwise.
                    await session.commit()
                else:
                    logger.debug("AD not configured — skipping scheduled sync tick")
        except Exception:  # never let a bad tick kill the loop
            logger.exception("scheduled AD sync tick failed")
        await _interruptible_sleep(stop_event, interval_minutes * 60)
    logger.info("AD-sync scheduler stopped")


__all__ = ["run_ad_sync_loop", "SCHEDULER_ACTOR_UPN"]
