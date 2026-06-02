from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime

import httpx
from sqlalchemy import select

from cockpit_api.config import settings
from cockpit_api.db import SessionFactory
from cockpit_api.models import Instance

logger = logging.getLogger(__name__)


async def poll_instance(client: httpx.AsyncClient, instance: Instance) -> None:
    health_url = instance.base_url.rstrip("/") + "/api/healthz"
    try:
        h = await client.get(health_url, timeout=settings.http_timeout_s)
        if h.status_code == 200:
            instance.last_health_status = "ok"
            instance.last_error = None
            data = h.json()
            if isinstance(data, dict) and "version" in data:
                instance.deployed_version = str(data["version"])
        else:
            instance.last_health_status = f"http_{h.status_code}"
            instance.last_error = h.text[:1000]
    except httpx.HTTPError as e:
        instance.last_health_status = "unreachable"
        instance.last_error = str(e)[:1000]
    instance.last_health_at = datetime.now(UTC)


async def poll_all_once() -> None:
    async with SessionFactory() as session, httpx.AsyncClient() as client:
        result = await session.execute(select(Instance))
        instances = list(result.scalars())
        for inst in instances:
            await poll_instance(client, inst)
        await session.commit()


async def health_poller_loop() -> None:
    while True:
        try:
            await poll_all_once()
        except Exception:
            logger.exception("health poller iteration failed")
        await asyncio.sleep(settings.health_poll_interval_s)
