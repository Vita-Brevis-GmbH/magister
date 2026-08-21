"""M6 Phase 1: /admin/modules read+write and its effect on /me/modules.

Skipped unless MAGISTER_TEST_DATABASE_URL is set (see integration conftest).
"""

from __future__ import annotations

from httpx import AsyncClient


async def test_defaults_are_school_profile(as_admin: AsyncClient) -> None:
    r = await as_admin.get("/admin/modules")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["instance_profile"] == "school"
    by_id = {m["id"]: m for m in body["modules"]}
    assert by_id["platform"]["enabled"] is True
    assert by_id["platform"]["toggleable"] is False
    assert by_id["school"]["enabled"] is True
    assert by_id["school"]["toggleable"] is True


async def test_disabling_school_hides_it_from_me_modules(as_admin: AsyncClient) -> None:
    r = await as_admin.put("/admin/modules", json={"module_overrides": {"school": False}})
    assert r.status_code == 200, r.text
    by_id = {m["id"]: m for m in r.json()["modules"]}
    assert by_id["school"]["enabled"] is False

    me = await as_admin.get("/me/modules")
    assert me.status_code == 200, me.text
    ids = [m["id"] for m in me.json()["modules"]]
    assert "platform" in ids
    assert "school" not in ids
    assert me.json()["profile"] == "school"


async def test_switching_profile_to_neutral_turns_school_off(as_admin: AsyncClient) -> None:
    r = await as_admin.put("/admin/modules", json={"instance_profile": "neutral"})
    assert r.status_code == 200, r.text
    assert r.json()["instance_profile"] == "neutral"
    by_id = {m["id"]: m for m in r.json()["modules"]}
    assert by_id["school"]["enabled"] is False


async def test_platform_cannot_be_toggled(as_admin: AsyncClient) -> None:
    r = await as_admin.put("/admin/modules", json={"module_overrides": {"platform": False}})
    assert r.status_code == 422


async def test_unknown_profile_is_rejected(as_admin: AsyncClient) -> None:
    r = await as_admin.put("/admin/modules", json={"instance_profile": "bogus"})
    assert r.status_code == 422


async def test_requires_admin(as_schulleitung_a: AsyncClient) -> None:
    r = await as_schulleitung_a.get("/admin/modules")
    assert r.status_code == 403
