"""The periodic AD-sync scheduler — M1 "AD … periodischer Sync funktional".

Drives :func:`run_ad_sync_loop` against ldap3 ``MOCK_SYNC`` + test Postgres and
asserts it populates ``ad_user_cache`` and emits ``ad_sync_completed`` without
anyone hitting the manual ``POST /admin/ad-sync`` trigger. A second test proves
that ticks are skipped (no client built, no audit) while AD is unconfigured.
"""

from __future__ import annotations

import asyncio
import contextlib
import uuid
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from magister_api.ad.client import AdClient
from magister_api.config import Settings
from magister_api.models.audit import AuditEvent
from magister_api.models.auth import AdUserCache
from magister_api.models.school import School
from magister_api.services.ad_sync_scheduler import run_ad_sync_loop

pytestmark = pytest.mark.postgres

DORA_GUID = "44444444-4444-4444-4444-444444444444"


def _le(guid_str: str) -> bytes:
    return uuid.UUID(guid_str).bytes_le


@pytest_asyncio.fixture
async def seeded_mock_client(app_settings: Settings) -> AsyncIterator[AdClient]:
    """An AdClient on a MOCK_SYNC connection pre-seeded with one student."""
    settings = app_settings.model_copy(
        update={"ad_use_mock": True, "ad_users_search_base": "DC=schule,DC=local"}
    )
    client = AdClient(settings)
    conn = client.mock_connection()
    conn.strategy.add_entry(
        "CN=Dora,OU=Students,OU=ALPHA,DC=schule,DC=local",
        {
            "objectClass": ["user"],
            "objectGUID": _le(DORA_GUID),
            "userPrincipalName": "dora@example.ch",
            "givenName": "Dora",
            "sn": "D.",
            "mail": "dora@example.ch",
            "userAccountControl": 0x200,
            "memberOf": [],
        },
    )
    yield client
    await client.aclose()


async def _wait_for_cached_upn(engine: AsyncEngine, upn: str, timeout_s: float = 5.0) -> bool:
    sm = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
    deadline = asyncio.get_running_loop().time() + timeout_s
    while asyncio.get_running_loop().time() < deadline:
        async with sm() as s:
            found = (
                await s.execute(select(AdUserCache.upn).where(AdUserCache.upn == upn))
            ).scalar_one_or_none()
        if found is not None:
            return True
        await asyncio.sleep(0.05)
    return False


@pytest.mark.asyncio
async def test_loop_populates_cache_and_audits(
    engine: AsyncEngine,
    app_settings: Settings,
    seeded_mock_client: AdClient,
    db_session: AsyncSession,
) -> None:
    db_session.add(School(name="Schule Alpha", kuerzel="ALPHA", scope_short="ALPHA"))
    await db_session.commit()

    base = app_settings.model_copy(
        update={"ad_use_mock": True, "ad_users_search_base": "DC=schule,DC=local"}
    )
    sm = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
    stop = asyncio.Event()
    task = asyncio.create_task(
        run_ad_sync_loop(base, sm, stop_event=stop, client_factory=lambda _s: seeded_mock_client)
    )
    try:
        assert await _wait_for_cached_upn(engine, "dora@example.ch"), "cache never populated"
    finally:
        stop.set()
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

    async with sm() as s:
        actions = list((await s.execute(select(AuditEvent.action))).scalars().all())
        actor = (
            await s.execute(
                select(AuditEvent.actor_upn).where(AuditEvent.action == "ad_sync_completed")
            )
        ).scalar_one()
    assert "ad_sync_completed" in actions
    assert actor == "system:ad-sync-scheduler"


@pytest.mark.asyncio
async def test_loop_skips_when_ad_unconfigured(
    engine: AsyncEngine,
    app_settings: Settings,
) -> None:
    base = app_settings.model_copy(
        update={"ad_use_mock": False, "ad_dcs": [], "ad_users_search_base": None}
    )
    sm = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
    stop = asyncio.Event()

    def _explode(_s: Settings) -> AdClient:
        raise AssertionError("AD client built despite unconfigured AD")

    task = asyncio.create_task(run_ad_sync_loop(base, sm, stop_event=stop, client_factory=_explode))
    # Give the loop time to run (and skip) at least one tick.
    await asyncio.sleep(0.3)
    stop.set()
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task

    async with sm() as s:
        audit_count = (await s.execute(select(func.count()).select_from(AuditEvent))).scalar_one()
    assert audit_count == 0
