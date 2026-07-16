"""Teacher provisioning import: duplicate-name guard + teacher password policy."""

from __future__ import annotations

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from magister_api.ad.client import AdClient
from magister_api.ad.password import MIN_LENGTH, count_charset_classes
from magister_api.config import Settings
from magister_api.models.app_settings import AppSettings
from magister_api.routers.imports import get_ad_client

pytestmark = pytest.mark.postgres

HEADER = (
    "given_name,surname,display_name,upn,sam_account_name,force_change,"
    "cannot_change_password,password_never_expires"
)


@pytest.fixture
def mock_ad(app_settings: Settings) -> AdClient:
    return AdClient(app_settings.model_copy(update={"ad_use_mock": True}))


@pytest_asyncio.fixture(autouse=True)
async def _teacher_ou(db_session: AsyncSession) -> None:
    row = await db_session.get(AppSettings, 1)
    assert row is not None
    row.ad_ou_teachers = "OU=Lehrpersonen,DC=schule,DC=local"
    await db_session.commit()


@pytest.mark.asyncio
async def test_duplicate_name_in_file_is_flagged_at_staging(
    as_smi_a: AsyncClient, school_a: int
) -> None:
    # Two teachers with the SAME display name but different UPNs → the CN
    # (CN=<display>,OU) would collide in AD. Staging must flag the second row.
    csv = (
        f"{HEADER}\n"
        "Anna,Muster,Anna Muster,anna.muster1@schule.ch,,true,,\n"
        "Anna,Muster,Anna Muster,anna.muster2@schule.ch,,true,,\n"
    )
    r = await as_smi_a.post("/imports?kind=teachers", files={"file": ("t.csv", csv, "text/csv")})
    assert r.status_code == 201, r.text
    job_id = r.json()["id"]
    detail = (await as_smi_a.get(f"/imports/{job_id}")).json()
    actions = [row["action"] for row in detail["rows"]]
    assert actions.count("create") == 1
    assert actions.count("error") == 1
    err_row = next(row for row in detail["rows"] if row["action"] == "error")
    assert any("duplicate name" in e.lower() for e in err_row["errors"])


@pytest.mark.asyncio
async def test_teacher_password_is_short_and_complex(
    as_smi_a: AsyncClient, app: FastAPI, school_a: int, mock_ad: AdClient
) -> None:
    csv = f"{HEADER}\nErika,Lehrer,,erika.lehrer@schule.ch,,true,,\n"
    r = await as_smi_a.post("/imports?kind=teachers", files={"file": ("t.csv", csv, "text/csv")})
    assert r.status_code == 201, r.text
    job_id = r.json()["id"]

    app.dependency_overrides[get_ad_client] = lambda: mock_ad
    try:
        r = await as_smi_a.post(f"/imports/{job_id}/apply")
    finally:
        app.dependency_overrides.pop(get_ad_client, None)
    assert r.status_code == 200, r.text
    creds = r.json()["credentials"]
    assert len(creds) == 1
    pw = creds[0]["password"]
    # Teacher rule: at most 12 chars (== AD minimum) and still strong (>=3 of 4
    # charset classes) — NOT the longer kid-friendly word password.
    assert len(pw) == MIN_LENGTH == 12
    assert count_charset_classes(pw) >= 3
    assert "-" not in pw or count_charset_classes(pw) >= 3  # not the word-hyphen format
