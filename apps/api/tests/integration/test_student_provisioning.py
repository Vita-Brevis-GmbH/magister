"""Integration tests for the ``students`` provisioning import (ADR 0006).

Creates NEW AD accounts via the mock AD backend, links them to a class, and
returns one-time credentials for the hand-out PDFs. Passwords must never be
persisted or audited.
"""

from __future__ import annotations

import io
import zipfile

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from magister_api.ad.client import AdClient
from magister_api.config import Settings
from magister_api.models.app_settings import AppSettings
from magister_api.models.audit import AuditEvent
from magister_api.models.auth import AdUserCache
from magister_api.models.class_membership import ClassMembership
from magister_api.models.school_class import SchoolClass
from magister_api.routers.admin_sync import get_ad_client

OU_OTHER = "OU=Schueler,OU=Volksschule,DC=schule,DC=local"
OU_Z3 = "OU=SekI,OU=Volksschule,DC=schule,DC=local"


@pytest.fixture
def mock_ad(app_settings: Settings) -> AdClient:
    return AdClient(app_settings.model_copy(update={"ad_use_mock": True}))


@pytest_asyncio.fixture(autouse=True)
async def _configure_ous(db_session: AsyncSession) -> None:
    row = await db_session.get(AppSettings, 1)
    assert row is not None
    row.ad_ou_students_zyklus3 = OU_Z3
    row.ad_ou_students_other = OU_OTHER
    await db_session.commit()


async def _seed_class(db_session: AsyncSession, school_id: int, name: str, jhg: int) -> None:
    db_session.add(SchoolClass(school_id=school_id, name=name, kuerzel=name, jahrgangsstufe=jhg))
    await db_session.commit()


STUDENTS_HEADER = (
    "given_name,surname,display_name,upn,sam_account_name,class,valid_from,force_change"
)


@pytest.mark.asyncio
async def test_template_students_csv(as_schulleitung_a: AsyncClient) -> None:
    r = await as_schulleitung_a.get("/imports/templates/students.csv")
    assert r.status_code == 200
    assert r.text.splitlines()[0] == STUDENTS_HEADER


@pytest.mark.asyncio
async def test_provision_students_end_to_end(
    as_schulleitung_a: AsyncClient,
    app: FastAPI,
    db_session: AsyncSession,
    school_a: int,
    mock_ad: AdClient,
) -> None:
    await _seed_class(db_session, school_a, "3a", 3)

    csv = (
        f"{STUDENTS_HEADER}\n"
        "Anna,Muster,,anna.muster@schule.ch,,3a,2026-08-12,true\n"
        "Ben,Beispiel,Ben B.,ben.beispiel@schule.ch,,3a,2026-08-12,false\n"
    )
    r = await as_schulleitung_a.post(
        "/imports?kind=students",
        files={"file": ("students.csv", csv, "text/csv")},
    )
    assert r.status_code == 201, r.text
    job = r.json()
    assert job["counts"]["create"] == 2
    assert job["counts"]["error"] == 0
    job_id = job["id"]

    app.dependency_overrides[get_ad_client] = lambda: mock_ad
    try:
        r = await as_schulleitung_a.post(f"/imports/{job_id}/apply")
    finally:
        app.dependency_overrides.pop(get_ad_client, None)

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["summary"]["applied"]["created"] == 2
    creds = body["credentials"]
    assert len(creds) == 2
    by_upn = {c["upn"]: c for c in creds}
    assert set(by_upn) == {"anna.muster@schule.ch", "ben.beispiel@schule.ch"}
    assert by_upn["anna.muster@schule.ch"]["force_change"] is True
    assert by_upn["ben.beispiel@schule.ch"]["force_change"] is False
    # Readable Word-Word-NN password shape.
    for c in creds:
        parts = c["password"].split("-")
        assert len(parts) == 3 and parts[2].isdigit()
        assert c["class_name"] == "3a"

    # Accounts + memberships landed in the DB.
    students = (
        (
            await db_session.execute(
                select(AdUserCache).where(
                    AdUserCache.kind == "student", AdUserCache.school_id == school_a
                )
            )
        )
        .scalars()
        .all()
    )
    assert {s.upn for s in students} == {"anna.muster@schule.ch", "ben.beispiel@schule.ch"}
    assert all(s.enabled for s in students)
    assert (
        await db_session.execute(select(func.count()).select_from(ClassMembership))
    ).scalar() == 2

    # Provisioning is audited, but the password never is.
    events = (
        (
            await db_session.execute(
                select(AuditEvent).where(AuditEvent.action == "student_provisioned")
            )
        )
        .scalars()
        .all()
    )
    assert len(events) == 2


@pytest.mark.asyncio
async def test_render_handouts_zip(as_schulleitung_a: AsyncClient) -> None:
    body = {
        "school_name": "Testschule",
        "credentials": [
            {
                "upn": "anna.muster@schule.ch",
                "display_name": "Anna Muster",
                "class_name": "3a",
                "password": "Tiger-Wolke-47",
                "force_change": True,
            },
            {
                "upn": "ben.beispiel@schule.ch",
                "display_name": "Ben Beispiel",
                "class_name": "3b",
                "password": "Panda-Segel-83",
                "force_change": False,
            },
        ],
    }
    r = await as_schulleitung_a.post("/imports/handouts", json=body)
    assert r.status_code == 200, r.text
    assert r.headers["content-type"] == "application/zip"
    zf = zipfile.ZipFile(io.BytesIO(r.content))
    assert set(zf.namelist()) == {"schueler-handouts.pdf", "klassen-uebersicht.pdf"}
    for name in zf.namelist():
        assert zf.read(name)[:4] == b"%PDF"


@pytest.mark.asyncio
async def test_handouts_empty_400(as_schulleitung_a: AsyncClient) -> None:
    r = await as_schulleitung_a.post("/imports/handouts", json={"credentials": []})
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_stage_error_when_ou_not_configured(
    as_schulleitung_a: AsyncClient, db_session: AsyncSession, school_a: int
) -> None:
    # Clear the "other" OU so a Zyklus-1/2 class cannot be provisioned.
    row = await db_session.get(AppSettings, 1)
    assert row is not None
    row.ad_ou_students_other = None
    await db_session.commit()
    await _seed_class(db_session, school_a, "3a", 3)

    csv = f"{STUDENTS_HEADER}\nAnna,Muster,,anna.muster@schule.ch,,3a,2026-08-12,true\n"
    r = await as_schulleitung_a.post(
        "/imports?kind=students",
        files={"file": ("students.csv", csv, "text/csv")},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["counts"]["error"] == 1
    assert "OU" in " ".join(body["rows"][0]["errors"])


@pytest.mark.asyncio
async def test_stage_error_when_upn_exists(
    as_schulleitung_a: AsyncClient, db_session: AsyncSession, school_a: int
) -> None:
    await _seed_class(db_session, school_a, "3a", 3)
    db_session.add(
        AdUserCache(
            ad_object_guid="00000000-0000-0000-0000-0000000000ff",
            school_id=school_a,
            upn="anna.muster@schule.ch",
            kind="student",
            enabled=True,
        )
    )
    await db_session.commit()

    csv = f"{STUDENTS_HEADER}\nAnna,Muster,,anna.muster@schule.ch,,3a,2026-08-12,true\n"
    r = await as_schulleitung_a.post(
        "/imports?kind=students",
        files={"file": ("students.csv", csv, "text/csv")},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["counts"]["error"] == 1
    assert "already exists" in " ".join(body["rows"][0]["errors"])
