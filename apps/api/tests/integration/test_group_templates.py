"""AD group templates (Zielrollen): CRUD, per-Standort filter, user-create use.

Skipped unless MAGISTER_TEST_DATABASE_URL is set (see integration conftest).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import TYPE_CHECKING

import pytest
import pytest_asyncio

from magister_api.ad.client import AdClient
from magister_api.config import Settings
from magister_api.models.school import School
from magister_api.routers.admin_sync import get_ad_client

if TYPE_CHECKING:
    from fastapi import FastAPI
    from httpx import AsyncClient
    from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.postgres

SEARCH_BASE = "DC=schule,DC=local"


@pytest_asyncio.fixture
async def mock_ad(app_settings: Settings) -> AsyncIterator[AdClient]:
    client = AdClient(
        app_settings.model_copy(update={"ad_use_mock": True, "ad_users_search_base": SEARCH_BASE})
    )
    yield client
    await client.aclose()


async def _set_teacher_ou(session: AsyncSession, school_id: int, ou: str) -> None:
    school = await session.get(School, school_id)
    assert school is not None
    school.ad_ou_teachers = ou
    await session.commit()


@pytest.mark.asyncio
async def test_crud_group_template(as_admin: AsyncClient, school_a: int) -> None:
    r = await as_admin.post(
        "/admin/group-templates",
        json={
            "name": "Tool-X Zugang",
            "description": "Zugang zu Tool X",
            "kind": "custom",
            "ad_groups": ["CN=Tool-X,DC=schule,DC=local"],
            "school_ids": [school_a],
        },
    )
    assert r.status_code == 201, r.text
    tpl = r.json()
    tid = tpl["id"]
    assert tpl["name"] == "Tool-X Zugang"
    assert tpl["ad_groups"] == ["CN=Tool-X,DC=schule,DC=local"]
    assert tpl["school_ids"] == [school_a]

    listed = (await as_admin.get("/admin/group-templates")).json()
    assert any(t["id"] == tid for t in listed)

    r = await as_admin.patch(
        f"/admin/group-templates/{tid}",
        json={"name": "Tool-X neu", "ad_groups": ["CN=Tool-X,DC=schule,DC=local", "CN=Y,DC=x"]},
    )
    assert r.status_code == 200, r.text
    assert r.json()["name"] == "Tool-X neu"
    assert len(r.json()["ad_groups"]) == 2

    assert (await as_admin.delete(f"/admin/group-templates/{tid}")).status_code == 204
    assert all(t["id"] != tid for t in (await as_admin.get("/admin/group-templates")).json())


@pytest.mark.asyncio
async def test_list_filter_by_school(as_admin: AsyncClient, school_a: int, school_b: int) -> None:
    a_only = (
        await as_admin.post(
            "/admin/group-templates",
            json={"name": "Nur A", "ad_groups": ["CN=A,DC=x"], "school_ids": [school_a]},
        )
    ).json()["id"]
    glob = (
        await as_admin.post(
            "/admin/group-templates",
            json={"name": "Global", "ad_groups": ["CN=G,DC=x"], "school_ids": []},
        )
    ).json()["id"]

    at_a = {
        t["id"] for t in (await as_admin.get(f"/admin/group-templates?school_id={school_a}")).json()
    }
    assert a_only in at_a and glob in at_a

    at_b = {
        t["id"] for t in (await as_admin.get(f"/admin/group-templates?school_id={school_b}")).json()
    }
    assert glob in at_b and a_only not in at_b


@pytest.mark.asyncio
async def test_create_user_with_template(
    as_admin: AsyncClient, app: FastAPI, mock_ad: AdClient, db_session: AsyncSession, school_a: int
) -> None:
    await _set_teacher_ou(db_session, school_a, "OU=Lehrer,DC=schule,DC=local")
    app.dependency_overrides[get_ad_client] = lambda: mock_ad
    tid = (
        await as_admin.post(
            "/admin/group-templates",
            json={"name": "Lehrer-Extra", "ad_groups": ["CN=Extra,DC=x"], "school_ids": [school_a]},
        )
    ).json()["id"]

    r = await as_admin.post(
        "/admin/ad-users",
        json={
            "given_name": "Timo",
            "surname": "Zielrolle",
            "sam_account_name": "tziel",
            "user_principal_name": "timo.ziel@schule.ch",
            "ou_key": "teacher",
            "school_id": school_a,
            "group_template_id": tid,
        },
    )
    assert r.status_code == 201, r.text


@pytest.mark.asyncio
async def test_create_user_template_not_found(
    as_admin: AsyncClient, app: FastAPI, mock_ad: AdClient, db_session: AsyncSession, school_a: int
) -> None:
    await _set_teacher_ou(db_session, school_a, "OU=Lehrer,DC=schule,DC=local")
    app.dependency_overrides[get_ad_client] = lambda: mock_ad
    r = await as_admin.post(
        "/admin/ad-users",
        json={
            "given_name": "Kein",
            "surname": "Template",
            "sam_account_name": "keintpl",
            "user_principal_name": "kein.tpl@schule.ch",
            "ou_key": "teacher",
            "school_id": school_a,
            "group_template_id": 999999,
        },
    )
    assert r.status_code == 404, r.text
    assert r.json()["detail"] == "group_template_not_found"


@pytest.mark.asyncio
async def test_create_user_template_not_for_school(
    as_admin: AsyncClient,
    app: FastAPI,
    mock_ad: AdClient,
    db_session: AsyncSession,
    school_a: int,
    school_b: int,
) -> None:
    await _set_teacher_ou(db_session, school_a, "OU=Lehrer,DC=schule,DC=local")
    app.dependency_overrides[get_ad_client] = lambda: mock_ad
    # Template offered only at school_b → refused for a create in school_a.
    tid = (
        await as_admin.post(
            "/admin/group-templates",
            json={"name": "Nur B", "ad_groups": ["CN=B,DC=x"], "school_ids": [school_b]},
        )
    ).json()["id"]
    r = await as_admin.post(
        "/admin/ad-users",
        json={
            "given_name": "Falsch",
            "surname": "Standort",
            "sam_account_name": "falsch",
            "user_principal_name": "falsch@schule.ch",
            "ou_key": "teacher",
            "school_id": school_a,
            "group_template_id": tid,
        },
    )
    assert r.status_code == 409, r.text
    assert r.json()["detail"] == "group_template_not_for_school"
