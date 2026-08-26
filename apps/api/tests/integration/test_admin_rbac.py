"""M6 #3 (ADR-0010): the dynamic role→capability matrix at /admin/rbac.

Skipped unless MAGISTER_TEST_DATABASE_URL is set (see integration conftest).
The RBAC roles + default matrix are seeded by the conftest, so the built-ins
behave exactly like the former static map until an admin edits them here.
"""

from __future__ import annotations

from collections.abc import Awaitable

from httpx import AsyncClient, Response
from sqlalchemy.ext.asyncio import AsyncSession


async def test_get_rbac_lists_roles_and_capabilities(as_admin: AsyncClient) -> None:
    r = await as_admin.get("/admin/rbac")
    assert r.status_code == 200, r.text
    body = r.json()
    # The full capability vocabulary is exposed (code-defined).
    assert "orgunit.manage" in body["capabilities"]
    assert "system.administer" in body["capabilities"]

    by_key = {role["key"]: role for role in body["roles"]}
    assert by_key["admin"]["is_admin"] is True
    assert by_key["admin"]["editable"] is False
    assert by_key["admin"]["deletable"] is False
    # schulleitung is a system role: caps editable, not deletable.
    assert by_key["schulleitung"]["is_system"] is True
    assert by_key["schulleitung"]["editable"] is True
    assert by_key["schulleitung"]["deletable"] is False
    assert "orgunit.manage" in by_key["schulleitung"]["capabilities"]
    # kl is derived: not editable, holds no coarse capability.
    assert by_key["kl"]["is_derived"] is True
    assert by_key["kl"]["editable"] is False
    assert by_key["kl"]["capabilities"] == []


async def test_requires_admin(as_schulleitung_a: AsyncClient) -> None:
    assert (await as_schulleitung_a.get("/admin/rbac")).status_code == 403


async def test_create_rename_delete_custom_role(as_admin: AsyncClient) -> None:
    r = await as_admin.post("/admin/rbac/roles", json={"key": "koordinator", "name": "Koordinator"})
    assert r.status_code == 201, r.text
    role = r.json()
    assert role["key"] == "koordinator"
    assert role["is_system"] is False
    assert role["editable"] is True
    assert role["deletable"] is True

    # Duplicate key → 409.
    dup = await as_admin.post("/admin/rbac/roles", json={"key": "koordinator", "name": "X"})
    assert dup.status_code == 409

    # Rename.
    rn = await as_admin.patch("/admin/rbac/roles/koordinator", json={"name": "Koordination"})
    assert rn.status_code == 200, rn.text
    assert rn.json()["name"] == "Koordination"

    # Delete.
    assert (await as_admin.delete("/admin/rbac/roles/koordinator")).status_code == 204
    by_key = {r["key"] for r in (await as_admin.get("/admin/rbac")).json()["roles"]}
    assert "koordinator" not in by_key


async def test_system_and_admin_role_invariants(as_admin: AsyncClient) -> None:
    # System role cannot be deleted or renamed.
    assert (await as_admin.delete("/admin/rbac/roles/schulleitung")).status_code == 409
    assert (
        await as_admin.patch("/admin/rbac/roles/schulleitung", json={"name": "X"})
    ).status_code == 409
    # admin capabilities are implicit and not editable.
    r = await as_admin.put(
        "/admin/rbac/roles/admin/capabilities", json={"capabilities": ["user.read"]}
    )
    assert r.status_code == 409
    # kl (derived) capabilities are not editable.
    r = await as_admin.put(
        "/admin/rbac/roles/kl/capabilities", json={"capabilities": ["user.read"]}
    )
    assert r.status_code == 409


async def test_unknown_capability_rejected(as_admin: AsyncClient) -> None:
    r = await as_admin.put(
        "/admin/rbac/roles/schulleitung/capabilities",
        json={"capabilities": ["not.a.capability"]},
    )
    assert r.status_code == 422


async def test_capability_edit_changes_authorization_live(
    as_admin: AsyncClient, as_schulleitung_a: AsyncClient
) -> None:
    # Baseline: schulleitung reaches /classes (needs orgunit.manage).
    assert (await as_schulleitung_a.get("/classes")).status_code == 200

    # Admin strips orgunit.manage from schulleitung (keeps user.read).
    r = await as_admin.put(
        "/admin/rbac/roles/schulleitung/capabilities",
        json={"capabilities": ["user.read"]},
    )
    assert r.status_code == 200, r.text

    # The matrix is loaded per request, so the change is immediate: /classes is
    # now forbidden, while a user.read surface stays reachable.
    assert (await as_schulleitung_a.get("/classes")).status_code == 403
    assert (await as_schulleitung_a.get("/users")).status_code == 200


async def test_grant_scope_rules_and_custom_role(
    as_admin: AsyncClient, db_session: AsyncSession, school_a: int
) -> None:
    from magister_api.models.auth import AdUserCache

    guid = "00000000-0000-0000-0000-0000000000ca"
    db_session.add(
        AdUserCache(
            ad_object_guid=guid,
            school_id=school_a,
            upn="target@example.ch",
            kind="teacher",
            enabled=True,
            ms_ds_consistency_guid=guid,
        )
    )
    await db_session.commit()

    def _grant(role: str, school_id: int | None) -> Awaitable[Response]:
        return as_admin.post(
            f"/admin/users/{guid}/roles", json={"role": role, "school_id": school_id}
        )

    # admin must be cross-school (school_id null).
    assert (await _grant("admin", school_a)).status_code == 422
    # a non-admin built-in role requires a school_id.
    assert (await _grant("schulleitung", None)).status_code == 422
    # derived kl is not assignable.
    assert (await _grant("kl", school_a)).status_code == 422
    # unknown role → 404.
    assert (await _grant("nope", school_a)).status_code == 404

    # A custom role, once created, is grantable like any other scoped role.
    await as_admin.post("/admin/rbac/roles", json={"key": "teamlead", "name": "Teamlead"})
    r = await _grant("teamlead", school_a)
    assert r.status_code == 201, r.text
    assert r.json()["role"] == "teamlead"
    # It shows up in the role-assignment overview.
    listing = (await as_admin.get("/admin/roles")).json()
    assert any(a["role"] == "teamlead" and a["ad_object_guid"] == guid for a in listing)
