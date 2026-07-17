"""Provisioning stores a password in the vault ONLY for cannot-change accounts.

A cannot-change-password account keeps its password, so a stored copy stays
correct; an account that can change it would leave a stale copy, so it is never
vaulted. Storage is additionally gated by the global password-store switch.
"""

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

# given_name,surname,display_name,upn,sam,class,valid_from,force_change,
# jahrgangsstufe,cannot_change_password,password_never_expires
HEADER = (
    "given_name,surname,display_name,upn,sam_account_name,class,valid_from,"
    "force_change,jahrgangsstufe,cannot_change_password,password_never_expires"
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


async def _set_switch(db_session: AsyncSession, on: bool) -> None:
    row = await db_session.get(AppSettings, 1)
    assert row is not None
    row.password_store_enabled = on
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


async def _row_for(db_session: AsyncSession, upn: str) -> AdUserCache:
    return (
        await db_session.execute(select(AdUserCache).where(AdUserCache.upn == upn))
    ).scalar_one()


@pytest.mark.asyncio
async def test_cannot_change_account_is_vaulted(
    as_smi_a: AsyncClient,
    app: FastAPI,
    db_session: AsyncSession,
    app_settings: Settings,
    school_a: int,
    mock_ad: AdClient,
    _student_ou: None,
) -> None:
    await _set_switch(db_session, True)
    await _make_class(db_session, school_a)

    # cannot_change_password = true  → gets vaulted.
    csv = f"{HEADER}\nAnna,Muster,,anna.muster@schule.ch,,3a,2026-08-12,false,3,true,true\n"
    body = await _apply(as_smi_a, app, mock_ad, csv)
    handout_pw = body["credentials"][0]["password"]

    db_session.expire_all()
    row = await _row_for(db_session, "anna.muster@schule.ch")
    assert row.store_password is True
    vault = PasswordVaultService(db_session, app_settings)
    assert await vault.get(row.ad_object_guid) == handout_pw


@pytest.mark.asyncio
async def test_changeable_account_is_not_vaulted(
    as_smi_a: AsyncClient,
    app: FastAPI,
    db_session: AsyncSession,
    app_settings: Settings,
    school_a: int,
    mock_ad: AdClient,
    _student_ou: None,
) -> None:
    await _set_switch(db_session, True)
    await _make_class(db_session, school_a)

    # cannot_change_password blank (=false) → NOT vaulted, even with switch on.
    csv = f"{HEADER}\nBea,Beispiel,,bea.beispiel@schule.ch,,3a,2026-08-12,true,3,,\n"
    await _apply(as_smi_a, app, mock_ad, csv)

    db_session.expire_all()
    row = await _row_for(db_session, "bea.beispiel@schule.ch")
    assert row.store_password is False
    vault = PasswordVaultService(db_session, app_settings)
    assert await vault.get(row.ad_object_guid) is None


@pytest.mark.asyncio
async def test_switch_off_stores_nothing(
    as_smi_a: AsyncClient,
    app: FastAPI,
    db_session: AsyncSession,
    app_settings: Settings,
    school_a: int,
    mock_ad: AdClient,
    _student_ou: None,
) -> None:
    await _set_switch(db_session, False)
    await _make_class(db_session, school_a)

    # cannot_change_password = true but global switch off → nothing stored.
    csv = f"{HEADER}\nCleo,Muster,,cleo.muster@schule.ch,,3a,2026-08-12,false,3,true,true\n"
    await _apply(as_smi_a, app, mock_ad, csv)

    db_session.expire_all()
    row = await _row_for(db_session, "cleo.muster@schule.ch")
    assert row.store_password is False
    vault = PasswordVaultService(db_session, app_settings)
    assert await vault.get(row.ad_object_guid) is None
