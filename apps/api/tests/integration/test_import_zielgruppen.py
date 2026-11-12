"""CSV-Import mit Zielgruppen: Standard-Zielgruppe des Zyklus, benannte, Fehler.

Ohne Spalte nimmt der Import die Standard-Zielgruppe der Kontoart (Schüler:
die des Zyklus); eine benannte gewinnt; eine unbekannte oder für eine andere
Kontoart ist ein Fehler beim Hochladen — nicht erst beim Anlegen.
"""

from __future__ import annotations

import re
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
from magister_api.models.school import School
from magister_api.models.school_class import CLASS_STATUS_ACTIVE, SchoolClass
from magister_api.routers.imports import get_ad_client
from magister_api.services.password_vault import PasswordVaultService

pytestmark = pytest.mark.postgres

HEADER = (
    "given_name,surname,display_name,upn,sam_account_name,class,valid_from,"
    "force_change,jahrgangsstufe,cannot_change_password,password_never_expires,zielgruppe"
)
TEACHER_HEADER = (
    "given_name,surname,display_name,upn,sam_account_name,force_change,"
    "cannot_change_password,password_never_expires,zielgruppe"
)
READABLE = re.compile(r"^[A-Z][a-z]+-[A-Z][a-z]+-\d{2,}$")


@pytest.fixture
def mock_ad(app_settings: Settings) -> AdClient:
    return AdClient(app_settings.model_copy(update={"ad_use_mock": True}))


@pytest_asyncio.fixture
async def _setup(db_session: AsyncSession, school_a: int) -> None:
    school = await db_session.get(School, school_a)
    assert school is not None
    school.ad_ou_students_zyklus3 = "OU=Sek,DC=schule,DC=local"
    school.ad_ou_students_other = "OU=Prim,DC=schule,DC=local"
    school.ad_ou_teachers = "OU=Lehrer,DC=schule,DC=local"
    settings = await db_session.get(AppSettings, 1)
    assert settings is not None
    settings.password_store_enabled = True
    db_session.add(
        SchoolClass(
            school_id=school_a,
            name="1a",
            kuerzel="1a",
            jahrgangsstufe=1,
            status=CLASS_STATUS_ACTIVE,
        )
    )
    await db_session.commit()


async def _defaults(as_admin: AsyncClient, school_id: int) -> dict[str, dict[str, Any]]:
    r = await as_admin.post("/admin/group-templates/defaults", json={"school_id": school_id})
    assert r.status_code == 200, r.text
    return {t["kind"]: t for t in r.json()}


async def _stage(as_client: AsyncClient, kind: str, csv: str, school_id: int) -> dict[str, Any]:
    r = await as_client.post(
        f"/imports?kind={kind}&school_id={school_id}",
        files={"file": ("x.csv", csv, "text/csv")},
    )
    assert r.status_code == 201, r.text
    return dict(r.json())


async def _apply(as_client: AsyncClient, app: FastAPI, mock_ad: AdClient, job_id: int) -> Any:
    app.dependency_overrides[get_ad_client] = lambda: mock_ad
    try:
        r = await as_client.post(f"/imports/{job_id}/apply")
    finally:
        app.dependency_overrides.pop(get_ad_client, None)
    assert r.status_code == 200, r.text
    return r.json()


async def _row(db_session: AsyncSession, upn: str) -> AdUserCache:
    db_session.expire_all()
    return (
        await db_session.execute(select(AdUserCache).where(AdUserCache.upn == upn))
    ).scalar_one()


@pytest.mark.asyncio
async def test_student_without_column_uses_the_zyklus_zielgruppe(
    as_admin: AsyncClient,
    app: FastAPI,
    db_session: AsyncSession,
    app_settings: Settings,
    school_a: int,
    mock_ad: AdClient,
    _setup: None,
) -> None:
    tpls = await _defaults(as_admin, school_a)
    # Klasse 1 = Zyklus 1: darf nicht ändern, Tresor, keine Änderung erzwungen.
    job = await _stage(
        as_admin,
        "students",
        f"{HEADER}\nLia,Klein,,lia.klein@schule.ch,,1a,2026-08-12,,1,,,\n",
        school_a,
    )
    body = await _apply(as_admin, app, mock_ad, job["id"])
    cred = body["credentials"][0]
    assert READABLE.match(cred["password"])
    assert cred["force_change"] is False
    row = await _row(db_session, "lia.klein@schule.ch")
    assert row.group_template_id == tpls["student_zyklus1"]["id"]
    assert row.cannot_change_password is True
    assert row.store_password is True
    assert (
        await PasswordVaultService(db_session, app_settings).get(row.ad_object_guid)
        == (cred["password"])
    )


@pytest.mark.asyncio
async def test_explicit_cell_beats_the_zielgruppe(
    as_admin: AsyncClient,
    app: FastAPI,
    db_session: AsyncSession,
    school_a: int,
    mock_ad: AdClient,
    _setup: None,
) -> None:
    await _defaults(as_admin, school_a)
    job = await _stage(
        as_admin,
        "students",
        f"{HEADER}\nBen,Klein,,ben.klein@schule.ch,,1a,2026-08-12,true,1,false,,\n",
        school_a,
    )
    body = await _apply(as_admin, app, mock_ad, job["id"])
    assert body["credentials"][0]["force_change"] is True
    row = await _row(db_session, "ben.klein@schule.ch")
    assert row.cannot_change_password is False
    # Ändern erlaubt → kein Tresor, auch wenn die Zielgruppe ihn vorsieht.
    assert row.store_password is False


@pytest.mark.asyncio
async def test_named_zielgruppe_is_used_and_unknown_is_a_staging_error(
    as_admin: AsyncClient,
    app: FastAPI,
    db_session: AsyncSession,
    school_a: int,
    mock_ad: AdClient,
    _setup: None,
) -> None:
    tpls = await _defaults(as_admin, school_a)
    custom = await as_admin.post(
        "/admin/group-templates",
        json={
            "name": "Lehrperson Plus",
            "kind": "teacher",
            "ad_groups": ["CN=Plus,DC=schule,DC=local"],
            "school_ids": [school_a],
            "password_profile": "complex",
        },
    )
    assert custom.status_code == 201, custom.text
    csv = (
        f"{TEACHER_HEADER}\n"
        "Eva,Plus,,eva.plus@schule.ch,,,,,lehrperson plus\n"
        "Udo,Weg,,udo.weg@schule.ch,,,,,Gibt es nicht\n"
        f"Sina,Falsch,,sina.falsch@schule.ch,,,,,{tpls['student_zyklus1']['name']}\n"
        "Tom,Standard,,tom.standard@schule.ch,,,,,\n"
    )
    job = await _stage(as_admin, "teachers", csv, school_a)
    detail = (await as_admin.get(f"/imports/{job['id']}")).json()
    by_upn = {r["raw_data"]["upn"]: r for r in detail["rows"]}
    assert by_upn["udo.weg@schule.ch"]["action"] == "error"
    assert "not found" in " ".join(by_upn["udo.weg@schule.ch"]["errors"])
    assert by_upn["sina.falsch@schule.ch"]["action"] == "error"
    assert "another account type" in " ".join(by_upn["sina.falsch@schule.ch"]["errors"])

    body = await _apply(as_admin, app, mock_ad, job["id"])
    creds = {c["upn"]: c for c in body["credentials"]}
    # Benannt (Gross/Klein egal): komplexes Passwort der eigenen Zielgruppe.
    assert len(creds["eva.plus@schule.ch"]["password"]) == 14
    eva = await _row(db_session, "eva.plus@schule.ch")
    assert eva.group_template_id == custom.json()["id"]
    # Ohne Spalte: Standard-Zielgruppe Lehrperson.
    tom = await _row(db_session, "tom.standard@schule.ch")
    assert tom.group_template_id == tpls["teacher"]["id"]
    assert len(creds["tom.standard@schule.ch"]["password"]) == 12
