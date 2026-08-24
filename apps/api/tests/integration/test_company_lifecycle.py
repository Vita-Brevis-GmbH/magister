"""M6 Phase 2: company on-/offboarding.

Skipped unless MAGISTER_TEST_DATABASE_URL is set (see integration conftest).
"""

from __future__ import annotations

from httpx import AsyncClient

_GUID = "33333333-3333-3333-3333-333333333333"


async def _dept(client: AsyncClient, name: str = "Onboard-Dept") -> int:
    r = await client.post("/departments", json={"name": name})
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def test_onboard_then_offboard(as_schulleitung_a: AsyncClient) -> None:
    did = await _dept(as_schulleitung_a)

    r = await as_schulleitung_a.post(
        "/company/onboard",
        json={"ad_object_guid": _GUID, "department_id": did, "role": "lead"},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["membership_id"] > 0
    assert body["manager_role_id"] is not None

    members = (await as_schulleitung_a.get(f"/departments/{did}/members")).json()
    managers = (await as_schulleitung_a.get(f"/departments/{did}/managers")).json()
    assert [m["ad_object_guid"] for m in members] == [_GUID]
    assert [m["ad_object_guid"] for m in managers] == [_GUID]

    r = await as_schulleitung_a.post("/company/offboard", json={"ad_object_guid": _GUID})
    assert r.status_code == 200, r.text
    assert r.json()["memberships_ended"] == 1
    assert r.json()["manager_roles_revoked"] == 1

    assert (await as_schulleitung_a.get(f"/departments/{did}/members")).json() == []
    assert (await as_schulleitung_a.get(f"/departments/{did}/managers")).json() == []


async def test_onboard_unknown_department_404(as_schulleitung_a: AsyncClient) -> None:
    r = await as_schulleitung_a.post(
        "/company/onboard", json={"ad_object_guid": _GUID, "department_id": 999999}
    )
    assert r.status_code == 404


async def test_offboard_respects_scope(
    as_schulleitung_a: AsyncClient, as_schulleitung_b: AsyncClient
) -> None:
    did = await _dept(as_schulleitung_a, name="Scoped-Dept")
    r = await as_schulleitung_a.post(
        "/company/onboard", json={"ad_object_guid": _GUID, "department_id": did}
    )
    assert r.status_code == 201, r.text

    # School B's unit admin cannot offboard a person out of A's department.
    r = await as_schulleitung_b.post("/company/offboard", json={"ad_object_guid": _GUID})
    assert r.status_code == 200, r.text
    assert r.json()["memberships_ended"] == 0
    assert r.json()["manager_roles_revoked"] == 0

    members = (await as_schulleitung_a.get(f"/departments/{did}/members")).json()
    assert [m["ad_object_guid"] for m in members] == [_GUID]
