"""M6 Phase 2: department memberships + manager (Kader) roles.

Skipped unless MAGISTER_TEST_DATABASE_URL is set (see integration conftest).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import TYPE_CHECKING

import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from magister_api.ad.client import AdClient
from magister_api.config import Settings
from magister_api.models.auth import AdUserCache
from magister_api.routers.admin_sync import get_ad_client

if TYPE_CHECKING:
    from fastapi import FastAPI

_GUID = "11111111-1111-1111-1111-111111111111"
_MGR = "22222222-2222-2222-2222-222222222222"


@pytest_asyncio.fixture(autouse=True)
async def _enable_company(db_session: AsyncSession) -> None:
    """The company module is off by default; enable it for these tests."""
    await db_session.execute(
        text(
            "UPDATE app_settings SET module_overrides = '{\"departments\": true}'::jsonb "
            "WHERE id = 1"
        )
    )
    await db_session.commit()


@pytest_asyncio.fixture
async def mock_ad(app_settings: Settings) -> AsyncIterator[AdClient]:
    client = AdClient(
        app_settings.model_copy(
            update={"ad_use_mock": True, "ad_users_search_base": "DC=schule,DC=local"}
        )
    )
    yield client
    await client.aclose()


async def _make_department(client: AsyncClient, name: str = "Team A") -> int:
    r = await client.post("/departments", json={"name": name})
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def test_membership_lifecycle(as_schulleitung_a: AsyncClient) -> None:
    did = await _make_department(as_schulleitung_a)

    r = await as_schulleitung_a.post(f"/departments/{did}/members", json={"ad_object_guid": _GUID})
    assert r.status_code == 201, r.text
    mid = r.json()["id"]
    assert r.json()["valid_to"] is None

    r = await as_schulleitung_a.get(f"/departments/{did}/members")
    assert r.status_code == 200
    assert [m["ad_object_guid"] for m in r.json()] == [_GUID]

    r = await as_schulleitung_a.delete(f"/departments/{did}/members/{mid}")
    assert r.status_code == 204

    r = await as_schulleitung_a.get(f"/departments/{did}/members")
    assert r.json() == []


async def test_list_reports_active_member_count(as_schulleitung_a: AsyncClient) -> None:
    did = await _make_department(as_schulleitung_a, name="Team Count")

    async def _count() -> int:
        rows = (await as_schulleitung_a.get("/departments")).json()
        return next(d["member_count"] for d in rows if d["id"] == did)

    assert await _count() == 0
    r = await as_schulleitung_a.post(f"/departments/{did}/members", json={"ad_object_guid": _GUID})
    mid = r.json()["id"]
    assert await _count() == 1
    await as_schulleitung_a.delete(f"/departments/{did}/members/{mid}")
    assert await _count() == 0


async def test_manager_lifecycle(as_schulleitung_a: AsyncClient) -> None:
    did = await _make_department(as_schulleitung_a, name="Team B")

    r = await as_schulleitung_a.post(
        f"/departments/{did}/managers", json={"ad_object_guid": _MGR, "role": "lead"}
    )
    assert r.status_code == 201, r.text
    rid = r.json()["id"]
    assert r.json()["role"] == "lead"

    r = await as_schulleitung_a.get(f"/departments/{did}/managers")
    assert [m["ad_object_guid"] for m in r.json()] == [_MGR]

    r = await as_schulleitung_a.delete(f"/departments/{did}/managers/{rid}")
    assert r.status_code == 204
    assert (await as_schulleitung_a.get(f"/departments/{did}/managers")).json() == []


async def test_cross_school_department_people_isolation(
    as_schulleitung_a: AsyncClient, as_schulleitung_b: AsyncClient
) -> None:
    did = await _make_department(as_schulleitung_a, name="Team C")
    # B cannot list or add members on A's department.
    assert (await as_schulleitung_b.get(f"/departments/{did}/members")).status_code == 404
    r = await as_schulleitung_b.post(f"/departments/{did}/members", json={"ad_object_guid": _GUID})
    assert r.status_code == 404


async def test_member_list_is_enriched_with_names(
    as_schulleitung_a: AsyncClient, db_session: AsyncSession, school_a: int
) -> None:
    from magister_api.models.auth import AdUserCache

    db_session.add(
        AdUserCache(
            ad_object_guid=_GUID,
            school_id=school_a,
            upn="mm@example.ch",
            display_name="Max Muster",
            kind="teacher",
            enabled=True,
            ms_ds_consistency_guid=_GUID,
        )
    )
    await db_session.commit()

    did = await _make_department(as_schulleitung_a, name="Team Enrich")
    await as_schulleitung_a.post(f"/departments/{did}/members", json={"ad_object_guid": _GUID})

    rows = (await as_schulleitung_a.get(f"/departments/{did}/members")).json()
    assert rows[0]["display_name"] == "Max Muster"
    assert rows[0]["upn"] == "mm@example.ch"


async def test_user_can_belong_to_multiple_departments(
    as_schulleitung_a: AsyncClient, as_schulleitung_b: AsyncClient
) -> None:
    d1 = await _make_department(as_schulleitung_a, name="Dept One")
    d2 = await _make_department(as_schulleitung_a, name="Dept Two")
    assert (
        await as_schulleitung_a.post(f"/departments/{d1}/members", json={"ad_object_guid": _GUID})
    ).status_code == 201
    assert (
        await as_schulleitung_a.post(f"/departments/{d2}/members", json={"ad_object_guid": _GUID})
    ).status_code == 201

    # User-centric view lists both departments, sorted by name.
    r = await as_schulleitung_a.get(f"/departments/for-user/{_GUID}")
    assert r.status_code == 200, r.text
    body = r.json()
    assert [d["name"] for d in body] == ["Dept One", "Dept Two"]
    assert {d["department_id"] for d in body} == {d1, d2}
    assert all(d["membership_id"] > 0 for d in body)

    # Scope isolation: B's unit admin sees none of A's departments for this user.
    assert (await as_schulleitung_b.get(f"/departments/for-user/{_GUID}")).json() == []


async def test_for_user_drops_ended_membership(as_schulleitung_a: AsyncClient) -> None:
    did = await _make_department(as_schulleitung_a, name="Dept End")
    r = await as_schulleitung_a.post(f"/departments/{did}/members", json={"ad_object_guid": _GUID})
    mid = r.json()["id"]
    assert len((await as_schulleitung_a.get(f"/departments/for-user/{_GUID}")).json()) == 1

    await as_schulleitung_a.delete(f"/departments/{did}/members/{mid}")
    assert (await as_schulleitung_a.get(f"/departments/for-user/{_GUID}")).json() == []


async def test_department_ad_groups_apply_and_revoke(
    as_schulleitung_a: AsyncClient, app: FastAPI, mock_ad: AdClient
) -> None:
    # A department carrying AD groups drives the AD-group apply (on add) and
    # revoke (on end) path. Mock directory → no real writes, but the code runs.
    app.dependency_overrides[get_ad_client] = lambda: mock_ad
    did = (
        await as_schulleitung_a.post(
            "/departments", json={"name": "IT", "ad_groups": ["CN=Tool,DC=schule,DC=local"]}
        )
    ).json()["id"]
    r = await as_schulleitung_a.post(f"/departments/{did}/members", json={"ad_object_guid": _GUID})
    assert r.status_code == 201, r.text
    mid = r.json()["id"]
    assert (await as_schulleitung_a.delete(f"/departments/{did}/members/{mid}")).status_code == 204


async def test_department_groups_revoke_keeps_shared(
    as_schulleitung_a: AsyncClient, app: FastAPI, mock_ad: AdClient
) -> None:
    # A group still granted by another active membership is not revoked on end.
    app.dependency_overrides[get_ad_client] = lambda: mock_ad
    shared = ["CN=Shared,DC=schule,DC=local"]
    d1 = (
        await as_schulleitung_a.post("/departments", json={"name": "D1", "ad_groups": shared})
    ).json()["id"]
    d2 = (
        await as_schulleitung_a.post("/departments", json={"name": "D2", "ad_groups": shared})
    ).json()["id"]
    m1 = (
        await as_schulleitung_a.post(f"/departments/{d1}/members", json={"ad_object_guid": _GUID})
    ).json()["id"]
    await as_schulleitung_a.post(f"/departments/{d2}/members", json={"ad_object_guid": _GUID})
    assert (await as_schulleitung_a.delete(f"/departments/{d1}/members/{m1}")).status_code == 204


async def test_department_group_change_propagates_to_members(
    as_schulleitung_a: AsyncClient, app: FastAPI, mock_ad: AdClient
) -> None:
    # Editing a department's AD groups reconciles every active member: the added
    # group is granted, the removed one revoked (mock directory → no-op writes,
    # but the reconcile path runs).
    app.dependency_overrides[get_ad_client] = lambda: mock_ad
    did = (
        await as_schulleitung_a.post(
            "/departments", json={"name": "Ops", "ad_groups": ["CN=Old,DC=schule,DC=local"]}
        )
    ).json()["id"]
    await as_schulleitung_a.post(f"/departments/{did}/members", json={"ad_object_guid": _GUID})

    r = await as_schulleitung_a.patch(
        f"/departments/{did}", json={"ad_groups": ["CN=New,DC=schule,DC=local"]}
    )
    assert r.status_code == 200, r.text
    assert r.json()["ad_groups"] == ["CN=New,DC=schule,DC=local"]


async def test_membership_add_mirrors_groups_to_user_cache(
    as_admin: AsyncClient, app: FastAPI, mock_ad: AdClient, db_session: AsyncSession, school_a: int
) -> None:
    # Assigning a member of a group-carrying department reflects the groups in
    # the user's cached ad_groups immediately (no AD sync needed) → the user
    # detail page shows them.
    db_session.add(
        AdUserCache(
            ad_object_guid=_GUID,
            school_id=school_a,
            upn="grp@example.ch",
            kind="company",
            enabled=True,
            ms_ds_consistency_guid=_GUID,
        )
    )
    await db_session.commit()
    app.dependency_overrides[get_ad_client] = lambda: mock_ad
    did = (
        await as_admin.post(
            "/departments",
            json={"name": "IT", "school_id": school_a, "ad_groups": ["CN=Tool,DC=schule,DC=local"]},
        )
    ).json()["id"]
    assert (
        await as_admin.post(f"/departments/{did}/members", json={"ad_object_guid": _GUID})
    ).status_code == 201
    groups = (await as_admin.get(f"/users/{_GUID}")).json()["ad_groups"]
    assert "CN=Tool,DC=schule,DC=local" in groups
