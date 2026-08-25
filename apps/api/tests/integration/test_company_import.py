"""Company-user provisioning import (#7): target OU + mail + mail aliases."""

from __future__ import annotations

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from magister_api.ad.client import AdClient
from magister_api.config import Settings
from magister_api.models.auth import AdUserCache
from magister_api.models.school import School
from magister_api.routers.imports import get_ad_client

pytestmark = pytest.mark.postgres

HEADER = (
    "given_name,surname,display_name,upn,sam_account_name,force_change,"
    "mail,mail_aliases,cannot_change_password,password_never_expires"
)


@pytest.fixture
def mock_ad(app_settings: Settings) -> AdClient:
    return AdClient(app_settings.model_copy(update={"ad_use_mock": True}))


@pytest_asyncio.fixture(autouse=True)
async def _company_ou(db_session: AsyncSession, school_a: int) -> None:
    for school in (await db_session.execute(select(School))).scalars().all():
        school.ad_ou_company_users = "OU=Mitarbeitende,OU=Firma,DC=firma,DC=local"
    await db_session.commit()


@pytest.mark.asyncio
async def test_company_import_provisions_with_mail_and_aliases(
    as_smi_a: AsyncClient, app: FastAPI, db_session: AsyncSession, mock_ad: AdClient
) -> None:
    csv = f"{HEADER}\nKarin,Kader,,karin.kader@firma.ch,,true,,k.kader@firma.ch;karin@firma.ch,,\n"
    r = await as_smi_a.post(
        "/imports?kind=company_users", files={"file": ("c.csv", csv, "text/csv")}
    )
    assert r.status_code == 201, r.text
    job_id = r.json()["id"]
    detail = (await as_smi_a.get(f"/imports/{job_id}")).json()
    assert [row["action"] for row in detail["rows"]] == ["create"]

    app.dependency_overrides[get_ad_client] = lambda: mock_ad
    try:
        r = await as_smi_a.post(f"/imports/{job_id}/apply")
    finally:
        app.dependency_overrides.pop(get_ad_client, None)
    assert r.status_code == 200, r.text
    assert len(r.json()["credentials"]) == 1

    row = (
        await db_session.execute(
            select(AdUserCache).where(AdUserCache.upn == "karin.kader@firma.ch")
        )
    ).scalar_one()
    assert row.kind == "company"
    assert row.mail == "karin.kader@firma.ch"  # blank mail cell → UPN
    assert set(row.mail_aliases) == {"k.kader@firma.ch", "karin@firma.ch"}


@pytest.mark.asyncio
async def test_company_import_requires_company_ou(
    as_smi_a: AsyncClient, db_session: AsyncSession
) -> None:
    for school in (await db_session.execute(select(School))).scalars().all():
        school.ad_ou_company_users = None
    await db_session.commit()

    csv = f"{HEADER}\nKarin,Kader,,karin.kader@firma.ch,,true,,,,\n"
    r = await as_smi_a.post(
        "/imports?kind=company_users", files={"file": ("c.csv", csv, "text/csv")}
    )
    assert r.status_code == 201, r.text
    detail = (await as_smi_a.get(f"/imports/{r.json()['id']}")).json()
    err = next(row for row in detail["rows"] if row["action"] == "error")
    assert any("company-users OU" in e for e in err["errors"])


@pytest.mark.asyncio
async def test_company_import_rejects_bad_alias(as_smi_a: AsyncClient) -> None:
    csv = f"{HEADER}\nKarin,Kader,,karin.kader@firma.ch,,true,,not-an-email,,\n"
    r = await as_smi_a.post(
        "/imports?kind=company_users", files={"file": ("c.csv", csv, "text/csv")}
    )
    assert r.status_code == 201, r.text
    detail = (await as_smi_a.get(f"/imports/{r.json()['id']}")).json()
    err = next(row for row in detail["rows"] if row["action"] == "error")
    assert any("alias" in e.lower() for e in err["errors"])


@pytest.mark.asyncio
async def test_company_import_needs_user_administer(as_schulleitung_a: AsyncClient) -> None:
    # Schulleitung has ORGUNIT_MANAGE but not USER_ADMINISTER → provisioning 403.
    csv = f"{HEADER}\nKarin,Kader,,karin.kader@firma.ch,,true,,,,\n"
    r = await as_schulleitung_a.post(
        "/imports?kind=company_users", files={"file": ("c.csv", csv, "text/csv")}
    )
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_company_template_downloadable(as_smi_a: AsyncClient) -> None:
    r = await as_smi_a.get("/imports/templates/company_users.csv")
    assert r.status_code == 200, r.text
    assert "mail_aliases" in r.text
