"""M6 Phase 2: /departments CRUD + school-scope isolation (company edition).

Skipped unless MAGISTER_TEST_DATABASE_URL is set (see integration conftest).
"""

from __future__ import annotations

import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


@pytest_asyncio.fixture(autouse=True)
async def _enable_company(db_session: AsyncSession) -> None:
    """The company module is off by default; enable it for these tests."""
    await db_session.execute(
        text("UPDATE app_settings SET module_overrides = '{\"company\": true}'::jsonb WHERE id = 1")
    )
    await db_session.commit()


async def test_create_list_get_patch_archive(as_schulleitung_a: AsyncClient) -> None:
    r = await as_schulleitung_a.post("/departments", json={"name": "Sekretariat", "kuerzel": "SEK"})
    assert r.status_code == 201, r.text
    dep = r.json()
    did = dep["id"]
    assert dep["name"] == "Sekretariat"
    assert dep["status"] == "active"

    r = await as_schulleitung_a.get("/departments")
    assert r.status_code == 200
    assert any(d["id"] == did for d in r.json())

    r = await as_schulleitung_a.get(f"/departments/{did}")
    assert r.status_code == 200

    r = await as_schulleitung_a.patch(f"/departments/{did}", json={"name": "Schulkommission"})
    assert r.status_code == 200, r.text
    assert r.json()["name"] == "Schulkommission"

    r = await as_schulleitung_a.delete(f"/departments/{did}")
    assert r.status_code == 204

    r = await as_schulleitung_a.get("/departments")
    assert all(d["id"] != did for d in r.json())


async def test_cross_school_isolation(
    as_schulleitung_a: AsyncClient, as_schulleitung_b: AsyncClient
) -> None:
    r = await as_schulleitung_a.post("/departments", json={"name": "A-Abteilung"})
    assert r.status_code == 201, r.text
    did = r.json()["id"]

    # School B's unit admin must not see or reach school A's department.
    r = await as_schulleitung_b.get(f"/departments/{did}")
    assert r.status_code == 404
    assert all(d["id"] != did for d in (await as_schulleitung_b.get("/departments")).json())


async def test_unauthenticated_rejected(client: AsyncClient) -> None:
    r = await client.get("/departments")
    assert r.status_code == 401
