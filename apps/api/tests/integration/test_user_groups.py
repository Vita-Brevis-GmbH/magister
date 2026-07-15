"""``PUT /users/{guid}/groups`` — per-user AD group membership editing."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select

from magister_api.ad.client import AdClient
from magister_api.config import Settings
from magister_api.models.auth import AdUserCache
from magister_api.routers.admin_sync import get_ad_client

if TYPE_CHECKING:
    from fastapi import FastAPI
    from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.postgres

STUDENT_GUID = "00000000-0000-0000-0000-0000000c0a02"
G_A = "CN=GroupA,OU=Groups,DC=schule,DC=local"
G_B = "CN=GroupB,OU=Groups,DC=schule,DC=local"
G_C = "CN=GroupC,OU=Groups,DC=schule,DC=local"


@pytest_asyncio.fixture
async def mock_ad(app_settings: Settings):
    settings = app_settings.model_copy(
        update={"ad_use_mock": True, "ad_users_search_base": "DC=schule,DC=local"}
    )
    client = AdClient(settings)
    conn = client.mock_connection()
    conn.strategy.add_entry(
        "CN=Max,OU=Students,DC=schule,DC=local",
        {
            "objectClass": ["user"],
            "objectGUID": uuid.UUID(STUDENT_GUID).bytes_le,
            "userPrincipalName": "max@schule.example.ch",
            "userAccountControl": 0x200,
        },
    )
    yield client
    await client.aclose()


async def _seed(db_session: AsyncSession, school_id: int, groups: list[str]) -> None:
    db_session.add(
        AdUserCache(
            ad_object_guid=STUDENT_GUID,
            school_id=school_id,
            upn="max@schule.example.ch",
            display_name="Max",
            sam_account_name="max",
            kind="student",
            enabled=True,
            ad_groups=groups,
        )
    )
    await db_session.flush()
    await db_session.commit()


class TestPutGroups:
    @pytest.mark.asyncio
    async def test_adds_and_removes_to_match_desired(
        self,
        app: FastAPI,
        as_smi_a: AsyncClient,
        db_session: AsyncSession,
        school_a: int,
        mock_ad: AdClient,
    ) -> None:
        await _seed(db_session, school_a, [G_A, G_B])
        app.dependency_overrides[get_ad_client] = lambda: mock_ad
        try:
            # Desired = {A, C}: keep A, remove B, add C.
            r = await as_smi_a.put(f"/users/{STUDENT_GUID}/groups", json={"groups": [G_A, G_C]})
            assert r.status_code == 200, r.text
            body = r.json()
            assert body["added"] == [G_C]
            assert body["removed"] == [G_B]
            assert body["failed"] == []
            assert body["groups"] == sorted([G_A, G_C])
        finally:
            app.dependency_overrides.pop(get_ad_client, None)

        # Cache reflects the new membership.
        row = (
            await db_session.execute(
                select(AdUserCache.ad_groups).where(AdUserCache.ad_object_guid == STUDENT_GUID)
            )
        ).scalar_one()
        assert sorted(row) == sorted([G_A, G_C])

    @pytest.mark.asyncio
    async def test_empty_list_removes_all(
        self,
        app: FastAPI,
        as_smi_a: AsyncClient,
        db_session: AsyncSession,
        school_a: int,
        mock_ad: AdClient,
    ) -> None:
        await _seed(db_session, school_a, [G_A, G_B])
        app.dependency_overrides[get_ad_client] = lambda: mock_ad
        try:
            r = await as_smi_a.put(f"/users/{STUDENT_GUID}/groups", json={"groups": []})
            assert r.status_code == 200, r.text
            assert r.json()["groups"] == []
        finally:
            app.dependency_overrides.pop(get_ad_client, None)

    @pytest.mark.asyncio
    async def test_no_change_is_noop(
        self,
        app: FastAPI,
        as_smi_a: AsyncClient,
        db_session: AsyncSession,
        school_a: int,
        mock_ad: AdClient,
    ) -> None:
        await _seed(db_session, school_a, [G_A])
        app.dependency_overrides[get_ad_client] = lambda: mock_ad
        try:
            r = await as_smi_a.put(f"/users/{STUDENT_GUID}/groups", json={"groups": [G_A]})
            assert r.status_code == 200, r.text
            body = r.json()
            assert body["added"] == [] and body["removed"] == []
            assert body["groups"] == [G_A]
        finally:
            app.dependency_overrides.pop(get_ad_client, None)

    @pytest.mark.asyncio
    async def test_rejects_unauthenticated(self, client: AsyncClient) -> None:
        # Unauthenticated state-changing request: refused (401 auth or 403 CSRF).
        r = await client.put(f"/users/{STUDENT_GUID}/groups", json={"groups": []})
        assert r.status_code in (401, 403)
