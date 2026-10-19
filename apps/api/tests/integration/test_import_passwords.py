"""Passwort-Import: bekannte Passwörter bestehender Konten ins AD und in den Tresor.

Das Passwort steht nie in ``raw_data`` (die Oberfläche zeigt es an), liegt bis
zum Übernehmen nur verschlüsselt in ``secret_enc`` und ist danach weg.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
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
from magister_api.models.audit import AuditEvent
from magister_api.models.auth import AdUserCache
from magister_api.models.import_job import ImportStagedRow
from magister_api.routers.imports import get_ad_client
from magister_api.services.password_vault import PasswordVaultService

pytestmark = pytest.mark.postgres

HEADER = "upn,password,force_change,cannot_change_password"
LIA = "00000000-0000-0000-0000-00000000a001"
TIM = "00000000-0000-0000-0000-00000000a002"
OFF = "00000000-0000-0000-0000-00000000a003"
FAR = "00000000-0000-0000-0000-00000000b001"


@pytest_asyncio.fixture
async def mock_ad(app_settings: Settings) -> AsyncIterator[AdClient]:
    client = AdClient(
        app_settings.model_copy(
            update={"ad_use_mock": True, "ad_users_search_base": "DC=schule,DC=local"}
        )
    )
    conn = client.mock_connection()
    for guid, cn in ((LIA, "Lia"), (TIM, "Tim")):
        conn.strategy.add_entry(
            f"CN={cn},OU=Prim,DC=schule,DC=local",
            {
                "objectClass": ["user"],
                "objectGUID": uuid.UUID(guid).bytes_le,
                "userPrincipalName": f"{cn.lower()}@schule.ch",
                "userAccountControl": 0x200,
            },
        )
    yield client
    await client.aclose()


@pytest_asyncio.fixture
async def _setup(db_session: AsyncSession, school_a: int, school_b: int) -> None:
    settings = await db_session.get(AppSettings, 1)
    assert settings is not None
    settings.password_store_enabled = True
    for guid, upn, school, enabled, cannot in (
        (LIA, "lia@schule.ch", school_a, True, True),
        (TIM, "tim@schule.ch", school_a, True, False),
        (OFF, "off@schule.ch", school_a, False, True),
        (FAR, "far@schule.ch", school_b, True, True),
    ):
        db_session.add(
            AdUserCache(
                ad_object_guid=guid,
                school_id=school,
                upn=upn,
                kind="student",
                enabled=enabled,
                cannot_change_password=cannot,
            )
        )
    await db_session.commit()


async def _stage(client: AsyncClient, csv: str, school_id: int) -> dict[str, Any]:
    r = await client.post(
        f"/imports?kind=passwords&school_id={school_id}",
        files={"file": ("pw.csv", csv, "text/csv")},
    )
    assert r.status_code == 201, r.text
    detail = await client.get(f"/imports/{r.json()['id']}")
    assert detail.status_code == 200, detail.text
    return dict(detail.json())


async def _apply(client: AsyncClient, app: FastAPI, ad: AdClient, job_id: int) -> Any:
    app.dependency_overrides[get_ad_client] = lambda: ad
    try:
        r = await client.post(f"/imports/{job_id}/apply")
    finally:
        app.dependency_overrides.pop(get_ad_client, None)
    assert r.status_code == 200, r.text
    return r.json()


async def _secrets(db_session: AsyncSession, job_id: int) -> list[bytes | None]:
    db_session.expire_all()
    return list(
        (
            await db_session.execute(
                select(ImportStagedRow.secret_enc).where(ImportStagedRow.job_id == job_id)
            )
        )
        .scalars()
        .all()
    )


@pytest.mark.asyncio
async def test_password_import_sets_ad_stores_vault_and_forgets_the_file(
    as_admin: AsyncClient,
    app: FastAPI,
    db_session: AsyncSession,
    app_settings: Settings,
    school_a: int,
    mock_ad: AdClient,
    _setup: None,
) -> None:
    csv = (
        f"{HEADER}\n"
        "lia@schule.ch,Sonne-Wald-42,,\n"
        "tim@schule.ch,Tiger-Berg-17,,\n"
        "off@schule.ch,Mond-See-11,,\n"
        "far@schule.ch,Fern-Weh-12,,\n"
        "nobody@schule.ch,Nie-Mand-13,,\n"
        "lia@schule.ch,Doppelt-34,,\n"
        "kein@schule.ch,,,\n"
        "lia2@schule.ch,Konflikt-55,true,true\n"
    )
    job = await _stage(as_admin, csv, school_a)
    by_row = {r["row_num"]: r for r in job["rows"]}
    # Das Passwort steht nirgends im Klartext in der Antwort.
    for secret in ("Sonne-Wald-42", "Tiger-Berg-17", "Nie-Mand-13"):
        assert secret not in str(job)
    assert all("password" not in r["raw_data"] for r in job["rows"])
    assert by_row[2]["action"] == "update"
    assert by_row[2]["errors"] == []
    # Tim darf ändern → Hinweis "nicht im Tresor", aber keine Fehlerzeile.
    assert by_row[3]["action"] == "update"
    assert "not stored in the vault" in by_row[3]["errors"][0]
    assert "disabled" in by_row[4]["errors"][0]
    assert "not found at this school" in by_row[5]["errors"][0]
    assert "not found at this school" in by_row[6]["errors"][0]
    assert "more than once" in by_row[7]["errors"][0]
    assert "password is required" in by_row[8]["errors"][0]
    assert by_row[9]["action"] == "error"
    assert any(s is not None for s in await _secrets(db_session, job["id"]))

    body = await _apply(as_admin, app, mock_ad, job["id"])
    assert body["summary"]["applied"]["updated"] == 2
    assert body["credentials"] == []
    assert await _secrets(db_session, job["id"]) == [None] * 8

    vault = PasswordVaultService(db_session, app_settings)
    lia = (
        await db_session.execute(select(AdUserCache).where(AdUserCache.ad_object_guid == LIA))
    ).scalar_one()
    assert lia.store_password is True
    assert await vault.get(LIA) == "Sonne-Wald-42"
    tim = (
        await db_session.execute(select(AdUserCache).where(AdUserCache.ad_object_guid == TIM))
    ).scalar_one()
    assert tim.store_password is False
    assert await vault.get(TIM) is None

    actions = list(
        (
            await db_session.execute(
                select(AuditEvent.action).where(AuditEvent.action == "password_imported")
            )
        )
        .scalars()
        .all()
    )
    assert len(actions) == 2


@pytest.mark.asyncio
async def test_cannot_change_column_enables_the_vault(
    as_admin: AsyncClient,
    app: FastAPI,
    db_session: AsyncSession,
    app_settings: Settings,
    school_a: int,
    mock_ad: AdClient,
    _setup: None,
) -> None:
    job = await _stage(as_admin, f"{HEADER}\ntim@schule.ch,Tiger-Berg-17,false,true\n", school_a)
    assert job["rows"][0]["errors"] == []
    await _apply(as_admin, app, mock_ad, job["id"])
    db_session.expire_all()
    tim = (
        await db_session.execute(select(AdUserCache).where(AdUserCache.ad_object_guid == TIM))
    ).scalar_one()
    assert tim.cannot_change_password is True
    assert tim.store_password is True
    assert await PasswordVaultService(db_session, app_settings).get(TIM) == "Tiger-Berg-17"


@pytest.mark.asyncio
async def test_vault_off_sets_ad_only_and_cancel_drops_the_secrets(
    as_admin: AsyncClient,
    db_session: AsyncSession,
    school_a: int,
    _setup: None,
) -> None:
    settings = await db_session.get(AppSettings, 1)
    assert settings is not None
    settings.password_store_enabled = False
    await db_session.commit()
    job = await _stage(as_admin, f"{HEADER}\nlia@schule.ch,Sonne-Wald-42,,\n", school_a)
    assert "vault is turned off" in job["rows"][0]["errors"][0]
    assert await _secrets(db_session, job["id"]) != [None]
    r = await as_admin.delete(f"/imports/{job['id']}")
    assert r.status_code in (200, 204), r.text
    assert await _secrets(db_session, job["id"]) == [None]


@pytest.mark.asyncio
async def test_schulleitung_may_not_import_passwords(
    as_schulleitung_a: AsyncClient,
    as_smi_a: AsyncClient,
    school_a: int,
    _setup: None,
) -> None:
    csv = f"{HEADER}\nlia@schule.ch,Sonne-Wald-42,,\n"
    r = await as_schulleitung_a.post(
        f"/imports?kind=passwords&school_id={school_a}",
        files={"file": ("pw.csv", csv, "text/csv")},
    )
    assert r.status_code == 403
    r = await as_smi_a.post(
        f"/imports?kind=passwords&school_id={school_a}",
        files={"file": ("pw.csv", csv, "text/csv")},
    )
    assert r.status_code == 201, r.text
