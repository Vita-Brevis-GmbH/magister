"""Admin single-user create/delete + demo-data purge endpoints."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING

import pytest
import pytest_asyncio
from sqlalchemy import select, update

from magister_api.ad.client import AdClient
from magister_api.config import Settings
from magister_api.models.app_settings import AppSettings
from magister_api.models.auth import AdUserCache
from magister_api.models.school import School
from magister_api.models.school_class import CLASS_STATUS_ACTIVE, SchoolClass
from magister_api.routers.admin_sync import get_ad_client
from magister_api.services.demo_data import DEMO_SCHOOL_KUERZEL

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


async def _set_teacher_ou(session: AsyncSession, ou: str) -> None:
    await session.execute(update(AppSettings).where(AppSettings.id == 1).values(ad_ou_teachers=ou))
    await session.commit()


@pytest.mark.asyncio
async def test_create_user_success(
    as_admin: AsyncClient, app: FastAPI, mock_ad: AdClient, db_session: AsyncSession
) -> None:
    await _set_teacher_ou(db_session, "OU=Lehrer,DC=schule,DC=local")
    app.dependency_overrides[get_ad_client] = lambda: mock_ad
    r = await as_admin.post(
        "/admin/ad-users",
        json={
            "given_name": "Hans",
            "surname": "Muster",
            "sam_account_name": "hmuster",
            "user_principal_name": "hans.muster@schule.ch",
            "ou_key": "teacher",
        },
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["temp_password"]
    assert body["force_change"] is True
    # Cache row was mirrored immediately.
    row = (
        await db_session.execute(
            select(AdUserCache).where(AdUserCache.ad_object_guid == body["ad_object_guid"])
        )
    ).scalar_one()
    assert row.kind == "teacher"
    assert row.upn == "hans.muster@schule.ch"


@pytest.mark.asyncio
async def test_create_user_ou_not_configured(
    as_admin: AsyncClient, app: FastAPI, mock_ad: AdClient
) -> None:
    app.dependency_overrides[get_ad_client] = lambda: mock_ad
    r = await as_admin.post(
        "/admin/ad-users",
        json={
            "given_name": "Kein",
            "surname": "OU",
            "sam_account_name": "keinou",
            "user_principal_name": "kein.ou@schule.ch",
            "ou_key": "teacher",
        },
    )
    assert r.status_code == 409, r.text
    assert r.json()["detail"] == "ou_not_configured"


@pytest.mark.asyncio
async def test_delete_user_success(
    as_admin: AsyncClient, app: FastAPI, mock_ad: AdClient, db_session: AsyncSession
) -> None:
    guid = "77777777-7777-7777-7777-777777777777"
    db_session.add(
        AdUserCache(
            ad_object_guid=guid,
            school_id=None,
            upn="tom@schule.ch",
            kind="student",
            enabled=True,
        )
    )
    await db_session.commit()
    mock_ad.mock_connection().strategy.add_entry(
        "CN=Tom,OU=Users,DC=schule,DC=local",
        {
            "objectClass": ["user"],
            "objectGUID": uuid.UUID(guid).bytes_le,
            "userPrincipalName": "tom@schule.ch",
            "userAccountControl": 512,
        },
    )
    app.dependency_overrides[get_ad_client] = lambda: mock_ad

    r = await as_admin.request("DELETE", f"/admin/ad-users/{guid}")
    assert r.status_code == 200, r.text
    assert r.json()["ad_disabled"] is True
    gone = (
        await db_session.execute(select(AdUserCache).where(AdUserCache.ad_object_guid == guid))
    ).scalar_one_or_none()
    assert gone is None


@pytest.mark.asyncio
async def test_delete_user_not_found(
    as_admin: AsyncClient, app: FastAPI, mock_ad: AdClient
) -> None:
    app.dependency_overrides[get_ad_client] = lambda: mock_ad
    r = await as_admin.request("DELETE", "/admin/ad-users/00000000-0000-0000-0000-000000000000")
    assert r.status_code == 404, r.text
    assert r.json()["detail"] == "user_not_found"


@pytest.mark.asyncio
async def test_purge_demo_data(as_admin: AsyncClient, db_session: AsyncSession) -> None:
    school = School(name="Schule Beispiel", kuerzel=DEMO_SCHOOL_KUERZEL, scope_short="BSP")
    db_session.add(school)
    await db_session.flush()
    db_session.add(
        SchoolClass(
            school_id=school.id,
            name="4a",
            kuerzel="4a",
            jahrgangsstufe=4,
            status=CLASS_STATUS_ACTIVE,
        )
    )
    db_session.add(
        AdUserCache(
            ad_object_guid=str(uuid.uuid4()),
            school_id=school.id,
            upn="demo@bsp.local",
            kind="student",
            enabled=True,
        )
    )
    await db_session.commit()

    r = await as_admin.post("/admin/demo-data/purge")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body == {"found": True, "schools": 1, "classes": 1, "users": 1}
    left = (
        await db_session.execute(select(School).where(School.kuerzel == DEMO_SCHOOL_KUERZEL))
    ).scalar_one_or_none()
    assert left is None


@pytest.mark.asyncio
async def test_purge_demo_data_none(as_admin: AsyncClient) -> None:
    r = await as_admin.post("/admin/demo-data/purge")
    assert r.status_code == 200, r.text
    assert r.json()["found"] is False
