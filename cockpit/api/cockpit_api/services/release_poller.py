from __future__ import annotations

import asyncio
import logging

import httpx
from sqlalchemy import select

from cockpit_api.config import settings
from cockpit_api.db import SessionFactory
from cockpit_api.models import Instance, InstanceChannel

logger = logging.getLogger(__name__)


def _manifest_url(channel: InstanceChannel) -> str:
    if channel is InstanceChannel.latest:
        return settings.release_manifest_url_latest
    return settings.release_manifest_url_stable


async def fetch_channel_version(client: httpx.AsyncClient, channel: InstanceChannel) -> str | None:
    url = _manifest_url(channel)
    try:
        r = await client.get(url, timeout=settings.http_timeout_s)
        if r.status_code != 200:
            return None
        data = r.json()
        if isinstance(data, dict) and isinstance(data.get("version"), str):
            return data["version"]
    except httpx.HTTPError:
        logger.warning("release manifest fetch failed: %s", url)
    return None


async def refresh_available_versions_once() -> None:
    async with httpx.AsyncClient() as client:
        versions: dict[InstanceChannel, str | None] = {}
        for ch in InstanceChannel:
            versions[ch] = await fetch_channel_version(client, ch)
    async with SessionFactory() as session:
        result = await session.execute(select(Instance))
        for inst in result.scalars():
            v = versions.get(inst.channel)
            if v is not None:
                inst.latest_available_version = v
        await session.commit()


async def release_poller_loop() -> None:
    while True:
        try:
            await refresh_available_versions_once()
        except Exception:
            logger.exception("release poller iteration failed")
        await asyncio.sleep(settings.release_poll_interval_s)
