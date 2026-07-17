"""Provisioning imports fill the password vault when the store switch is on."""

from __future__ import annotations

from typing import Any

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from magister_api.ad.client import AdClient
from magister_api.config import Settings
from magister_api.models.app_settings import AppSettings
from magister_api.models.auth import AdUserCache
from magister_api.routers.imports import get_ad_client
from magister_api.services.password_vault import PasswordVaultService

pytestmark = pytest.mark.postgres

STUDENT_HEADER = (
    "given_name,surname,display_name,upn,sam_account_name,class,valid_from,"
    "force_change,jahrgangsstufe,cannot_change_password,password_never_expires,store_password"
)


@pytest.fixture
def mock_ad(app_settings: Settings) -> AdClient:
    return AdClient(app_settings.model_copy(update={"ad_use_mock": True}))


@pytest_asyncio.fixture
async def _student_ou(db_session: AsyncSession) -> None:
    row = await db_session.get(AppSettings, 1)
    assert row is not None
    row.ad_ou_students_zyklus3 = "OU=Sek,DC=schule,DC=local"
    row.ad_ou_students_other = "OU=Prim,DC=schule,DC=local"
    await db_session.commit()


async def _make_class(db_session: AsyncSession, school_id: int) -> None:
    from magister_api.models.school_class import CLASS_STATUS_ACTIVE, SchoolClass

    db_session.add(
        SchoolClass(
            school_id=school_id,
            name="3a",
            kuerzel="3a",
            jahrgangsstufe=3,
            status=CLASS_STATUS_ACTIVE,
        )
    )
    await db_session.commit()


async def _apply(as_client: AsyncClient, app: FastAPI, mock_ad: AdClient, csv: str) -> Any:
    r = await as_client.post("/imports?kind=students", files={"file": ("s.csv", csv, "text/csv")})
    assert r.status_code == 201, r.text
    job_id = r.json()["id"]
    app.dependency_overrides[get_ad_client] = lambda: mock_ad
    try:
        r = await as_client.post(f"/imports/{job_id}/apply")
    finally:
        app.dependency_overrides.pop(get_ad_client, None)
    assert r.status_code == 200, r.text
    return r.json()


async def _guid_for(db_session: AsyncSession, upn: str) -> str:
    guid = (
        await db_session.execute(select(AdUserCache.ad_object_guid).where(AdUserCache.upn == upn))
    ).scalar_one()
    return str(guid)


@pytest.mark.asyncio
async def test_switch_on_default_fills_vault(
    as_smi_a: AsyncClient,
    app: FastAPI,
    db_session: AsyncSession,
    app_settings: Settings,
    school_a: int,
    mock_ad: AdClient,
    _student_ou: None,
) -> None:
    # Global switch ON; store_password column left blank → follows the switch.
    row = await db_session.get(AppSettings, 1)
    assert row is not None
    row.password_store_enabled = True
    await db_session.commit()
    await _make_class(db_session, school_a)

    csv = f"{STUDENT_HEADER}\nAnna,Muster,,anna.muster@schule.ch,,3a,2026-08-12,true,3,,,\n"
    body = await _apply(as_smi_a, app, mock_ad, csv)
    handout_pw = body["credentials"][0]["password"]

    db_session.expire_all()
    guid = await _guid_for(db_session, "anna.muster@schule.ch")
    vault = PasswordVaultService(db_session, app_settings)
    assert await vault.get(guid) == handout_pw

    stored = (
        await db_session.execute(
            select(AdUserCache.store_password).where(AdUserCache.ad_object_guid == guid)
        )
    ).scalar_one()
    assert stored is True


@pytest.mark.asyncio
async def test_switch_off_does_not_store_even_if_column_true(
    as_smi_a: AsyncClient,
    app: FastAPI,
    db_session: AsyncSession,
    app_settings: Settings,
    school_a: int,
    mock_ad: AdClient,
    _student_ou: None,
) -> None:
    row = await db_session.get(AppSettings, 1)
    assert row is not None
    row.password_store_enabled = False
    await db_session.commit()
    await _make_class(db_session, school_a)

    csv = f"{STUDENT_HEADER}\nBea,Beispiel,,bea.beispiel@schule.ch,,3a,2026-08-12,true,3,,,true\n"
    await _apply(as_smi_a, app, mock_ad, csv)

    db_session.expire_all()
    guid = await _guid_for(db_session, "bea.beispiel@schule.ch")
    vault = PasswordVaultService(db_session, app_settings)
    # Per-user flag captured (True) but nothing encrypted while the switch is off.
    assert await vault.get(guid) is None
