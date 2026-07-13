"""End-to-end AD sync + listing — DoD coverage for issue #3.

Uses ldap3 ``MOCK_SYNC`` so we don't need a real DC. The mock connection is
seeded with two users in school A and one in school B; we verify the sync
populates ``ad_user_cache``, the listing endpoint respects Schul-Scope, and
the manual trigger emits ``ad_sync_completed``.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from magister_api.ad.client import AdClient
from magister_api.config import Settings
from magister_api.models.audit import AuditEvent
from magister_api.models.auth import AdUserCache
from magister_api.routers.admin_sync import get_ad_client

if TYPE_CHECKING:
    from fastapi import FastAPI
    from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.postgres


# Stable LE-bytes for objectGUID so tests compare equal across runs.
ANNA_GUID = "11111111-1111-1111-1111-111111111111"
BENO_GUID = "22222222-2222-2222-2222-222222222222"
CARLA_GUID = "33333333-3333-3333-3333-333333333333"


def _le(guid_str: str) -> bytes:
    return uuid.UUID(guid_str).bytes_le


@pytest_asyncio.fixture
async def mock_ad_client(app_settings: Settings):
    """An AdClient bound to a MOCK_SYNC connection, pre-seeded with three users."""
    settings = app_settings.model_copy(
        update={
            "ad_use_mock": True,
            "ad_users_search_base": "DC=schule,DC=local",
        }
    )
    client = AdClient(settings)

    conn = client.mock_connection()
    for guid, upn, given, sn, dn, member_of, enabled in [
        (
            ANNA_GUID,
            "anna@example.ch",
            "Anna",
            "A.",
            "CN=Anna,OU=Students,OU=ALPHA,DC=schule,DC=local",
            [],
            True,
        ),
        (
            BENO_GUID,
            "beno@example.ch",
            "Beno",
            "B.",
            "CN=Beno,OU=Students,OU=ALPHA,DC=schule,DC=local",
            [],
            True,
        ),
        (
            CARLA_GUID,
            "carla@example.ch",
            "Carla",
            "C.",
            "CN=Carla,OU=Teachers,OU=BETA,DC=schule,DC=local",
            ["CN=Teachers,OU=Groups"],
            True,
        ),
    ]:
        conn.strategy.add_entry(
            dn,
            {
                "objectClass": ["user"],
                "objectGUID": _le(guid),
                "userPrincipalName": upn,
                "givenName": given,
                "sn": sn,
                "mail": upn,
                "userAccountControl": 0x200 | (0 if enabled else 0x0002),
                "memberOf": member_of,
            },
        )
    yield client
    await client.aclose()


class TestSyncRoundTrip:
    @pytest.mark.asyncio
    async def test_admin_trigger_populates_cache_with_school_partition(
        self,
        app: FastAPI,
        as_admin: AsyncClient,
        mock_ad_client: AdClient,
        engine: AsyncEngine,
        db_session: AsyncSession,
    ) -> None:
        # Seed two schools whose scope_short matches the OU components in our DNs.
        from magister_api.models.school import School

        db_session.add_all(
            [
                School(name="Schule Alpha", kuerzel="ALPHA", scope_short="ALPHA"),
                School(name="Schule Beta", kuerzel="BETA", scope_short="BETA"),
            ]
        )
        await db_session.flush()
        await db_session.commit()

        app.dependency_overrides[get_ad_client] = lambda: mock_ad_client
        try:
            r = await as_admin.post("/admin/ad-sync")
        finally:
            app.dependency_overrides.pop(get_ad_client, None)

        assert r.status_code == 200, r.text
        body = r.json()
        assert body["synced_count"] == 3
        # School-Partition: 2 in Alpha, 1 in Beta.
        assert sum(body["school_partition"].values()) == 3

        sm = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
        async with sm() as s:
            cached_upns = sorted((await s.execute(select(AdUserCache.upn))).scalars().all())
        # The as_admin fixture seeded admin@example.ch separately; AD sync
        # adds Anna/Beno/Carla on top.
        for expected in ("anna@example.ch", "beno@example.ch", "carla@example.ch"):
            assert expected in cached_upns

        async with sm() as s:
            actions = list((await s.execute(select(AuditEvent.action))).scalars().all())
        assert "ad_sync_completed" in actions


class TestListingScope:
    @pytest.mark.asyncio
    async def test_schulleitung_a_only_sees_school_a_users(
        self,
        as_schulleitung_a: AsyncClient,
        as_admin: AsyncClient,
        app: FastAPI,
        mock_ad_client: AdClient,
        db_session: AsyncSession,
        school_a: int,
        school_b: int,
    ) -> None:
        # Override the schools so our seeded scope_short matches the school for
        # the as_schulleitung_a fixture.
        from magister_api.models.school import School

        a = await db_session.get(School, school_a)
        b = await db_session.get(School, school_b)
        assert a is not None and b is not None
        a.scope_short = "ALPHA"
        b.scope_short = "BETA"
        await db_session.commit()

        app.dependency_overrides[get_ad_client] = lambda: mock_ad_client
        try:
            r = await as_admin.post("/admin/ad-sync")
            assert r.status_code == 200, r.text
        finally:
            app.dependency_overrides.pop(get_ad_client, None)

        # Schulleitung A sees only Anna + Beno (school A) plus their own
        # cache row (also in school A from the fixture).
        r = await as_schulleitung_a.get("/users")
        assert r.status_code == 200, r.text
        body = r.json()
        upns = sorted(u["upn"] for u in body["items"])
        assert "anna@example.ch" in upns
        assert "beno@example.ch" in upns
        assert "carla@example.ch" not in upns  # Beta is out of A's scope
        assert body["last_sync_at"] is not None

    @pytest.mark.asyncio
    async def test_filter_kind_teacher_only(
        self,
        as_admin: AsyncClient,
        app: FastAPI,
        mock_ad_client: AdClient,
    ) -> None:
        app.dependency_overrides[get_ad_client] = lambda: mock_ad_client
        try:
            await as_admin.post("/admin/ad-sync")
        finally:
            app.dependency_overrides.pop(get_ad_client, None)

        r = await as_admin.get("/users?kind=teacher")
        assert r.status_code == 200
        body = r.json()
        upns = [u["upn"] for u in body["items"]]
        assert upns == ["carla@example.ch"]

    @pytest.mark.asyncio
    async def test_search_substring(
        self,
        as_admin: AsyncClient,
        app: FastAPI,
        mock_ad_client: AdClient,
    ) -> None:
        app.dependency_overrides[get_ad_client] = lambda: mock_ad_client
        try:
            await as_admin.post("/admin/ad-sync")
        finally:
            app.dependency_overrides.pop(get_ad_client, None)

        r = await as_admin.get("/users?search=ann")
        body = r.json()
        upns = [u["upn"] for u in body["items"]]
        assert upns == ["anna@example.ch"]

    @pytest.mark.asyncio
    async def test_pagination(
        self,
        as_admin: AsyncClient,
        app: FastAPI,
        mock_ad_client: AdClient,
    ) -> None:
        app.dependency_overrides[get_ad_client] = lambda: mock_ad_client
        try:
            await as_admin.post("/admin/ad-sync")
        finally:
            app.dependency_overrides.pop(get_ad_client, None)

        # Total = 4 (3 from AD + the as_admin fixture's own admin row).
        r = await as_admin.get("/users?limit=2&offset=0")
        body = r.json()
        assert len(body["items"]) == 2
        assert body["total"] == 4

        r = await as_admin.get("/users?limit=2&offset=2")
        body = r.json()
        assert len(body["items"]) == 2
        assert body["total"] == 4


class TestAdUnavailable:
    @pytest.mark.asyncio
    async def test_503_when_pool_exhausted(
        self,
        as_admin: AsyncClient,
        app: FastAPI,
        app_settings: Settings,
    ) -> None:
        # Live mode with a search base but no DCs configured triggers
        # AdUnavailableError immediately. The sync endpoint now surfaces the
        # specific reason (ad_config = "MAGISTER_AD_DCS is empty") instead of a
        # blanket "ad_unavailable".
        broken_settings = app_settings.model_copy(
            update={
                "ad_use_mock": False,
                "ad_dcs": [],
                "ad_users_search_base": "DC=schule,DC=local",
            }
        )
        broken_client = AdClient(broken_settings)
        app.dependency_overrides[get_ad_client] = lambda: broken_client
        try:
            r = await as_admin.post("/admin/ad-sync")
        finally:
            app.dependency_overrides.pop(get_ad_client, None)
        assert r.status_code == 503
        assert r.json()["detail"] == "ad_config"


class TestRbac:
    @pytest.mark.asyncio
    async def test_users_listing_requires_schulleitung(self, client: AsyncClient) -> None:
        r = await client.get("/users")
        assert r.status_code == 401

    @pytest.mark.asyncio
    async def test_admin_sync_requires_admin(self, as_schulleitung_a: AsyncClient) -> None:
        r = await as_schulleitung_a.post("/admin/ad-sync")
        assert r.status_code == 403
