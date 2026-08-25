"""M6 Phase 2: department memberships + manager (Kader) roles.

Skipped unless MAGISTER_TEST_DATABASE_URL is set (see integration conftest).
"""

from __future__ import annotations

import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

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
