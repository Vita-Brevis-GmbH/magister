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
from magister_api.models.audit import AuditEvent
from magister_api.models.auth import AdUserCache
from magister_api.models.class_membership import ClassMembership
from magister_api.models.school import School
from magister_api.models.school_class import SchoolClass
from magister_api.routers.admin_sync import get_ad_client

OU_OTHER = "OU=Schueler,OU=Volksschule,DC=schule,DC=local"
OU_Z3 = "OU=SekI,OU=Volksschule,DC=schule,DC=local"
OU_TEACHERS = "OU=Lehrpersonen,OU=Volksschule,DC=schule,DC=local"

TEACHERS_HEADER = (
    "given_name,surname,display_name,upn,sam_account_name,force_change,"
    "cannot_change_password,password_never_expires"
)


@pytest.fixture
def mock_ad(app_settings: Settings) -> AdClient:
    return AdClient(app_settings.model_copy(update={"ad_use_mock": True}))


@pytest_asyncio.fixture(autouse=True)
async def _configure_ous(db_session: AsyncSession, school_a: int) -> None:
    # OUs are now per-school; configure every school in the fixture DB. Depends
    # on school_a so it runs after the school(s) exist.
    for school in (await db_session.execute(select(School))).scalars().all():
        school.ad_ou_students_zyklus3 = OU_Z3
        school.ad_ou_students_other = OU_OTHER
        school.ad_ou_teachers = OU_TEACHERS
    await db_session.commit()


async def _seed_class(db_session: AsyncSession, school_id: int, name: str, jhg: int) -> None:
    db_session.add(SchoolClass(school_id=school_id, name=name, kuerzel=name, jahrgangsstufe=jhg))
    await db_session.commit()


STUDENTS_HEADER = (
    "given_name,surname,display_name,upn,sam_account_name,"
    "class,valid_from,force_change,jahrgangsstufe,"
    "cannot_change_password,password_never_expires"
)


@pytest.mark.asyncio
async def test_template_students_csv(as_schulleitung_a: AsyncClient) -> None:
    r = await as_schulleitung_a.get("/imports/templates/students.csv")
    assert r.status_code == 200
    assert r.text.splitlines()[0] == STUDENTS_HEADER


@pytest.mark.asyncio
async def test_provision_students_end_to_end(
    as_smi_a: AsyncClient,
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
    r = await as_smi_a.post(
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
        r = await as_smi_a.post(f"/imports/{job_id}/apply")
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
async def test_student_import_sets_own_grade(
    as_smi_a: AsyncClient,
    app: FastAPI,
    db_session: AsyncSession,
    school_a: int,
    mock_ad: AdClient,
) -> None:
    # Multi-grade class (1–3); explicit per-student grade vs blank (→ class lower).
    await _seed_class(db_session, school_a, "M13", 1)
    csv = (
        f"{STUDENTS_HEADER}\n"
        "Anna,Muster,,anna.muster@schule.ch,,M13,2026-08-12,true,2\n"
        "Ben,Beispiel,,ben.beispiel@schule.ch,,M13,2026-08-12,false,\n"
    )
    r = await as_smi_a.post("/imports?kind=students", files={"file": ("s.csv", csv, "text/csv")})
    assert r.status_code == 201, r.text
    job_id = r.json()["id"]
    app.dependency_overrides[get_ad_client] = lambda: mock_ad
    try:
        r = await as_smi_a.post(f"/imports/{job_id}/apply")
    finally:
        app.dependency_overrides.pop(get_ad_client, None)
    assert r.status_code == 200, r.text

    rows = {
        s.upn: s
        for s in (
            (await db_session.execute(select(AdUserCache).where(AdUserCache.kind == "student")))
            .scalars()
            .all()
        )
    }
    assert rows["anna.muster@schule.ch"].jahrgangsstufe == 2  # explicit
    assert rows["ben.beispiel@schule.ch"].jahrgangsstufe == 1  # class lower grade


@pytest.mark.asyncio
async def test_template_teachers_csv(as_smi_a: AsyncClient) -> None:
    r = await as_smi_a.get("/imports/templates/teachers.csv")
    assert r.status_code == 200
    assert r.text.splitlines()[0] == TEACHERS_HEADER


@pytest.mark.asyncio
async def test_provision_teachers_end_to_end(
    as_smi_a: AsyncClient,
    app: FastAPI,
    db_session: AsyncSession,
    school_a: int,
    mock_ad: AdClient,
) -> None:
    csv = (
        f"{TEACHERS_HEADER}\n"
        "Erika,Lehrer,,erika.lehrer@schule.ch,,true\n"
        "Max,Kollege,Max K.,max.kollege@schule.ch,max.kollege,false\n"
    )
    r = await as_smi_a.post("/imports?kind=teachers", files={"file": ("t.csv", csv, "text/csv")})
    assert r.status_code == 201, r.text
    assert r.json()["counts"]["create"] == 2
    job_id = r.json()["id"]

    app.dependency_overrides[get_ad_client] = lambda: mock_ad
    try:
        r = await as_smi_a.post(f"/imports/{job_id}/apply")
    finally:
        app.dependency_overrides.pop(get_ad_client, None)
    assert r.status_code == 200, r.text
    assert r.json()["summary"]["applied"]["created"] == 2

    teachers = (
        (await db_session.execute(select(AdUserCache).where(AdUserCache.kind == "teacher")))
        .scalars()
        .all()
    )
    # Subset check — the SMI fixture user is itself kind=teacher.
    assert {"erika.lehrer@schule.ch", "max.kollege@schule.ch"} <= {tt.upn for tt in teachers}
    # Teachers get no class membership from this import.
    assert (
        await db_session.execute(select(func.count()).select_from(ClassMembership))
    ).scalar() == 0
    events = (
        (
            await db_session.execute(
                select(AuditEvent).where(AuditEvent.action == "teacher_provisioned")
            )
        )
        .scalars()
        .all()
    )
    assert len(events) == 2


@pytest.mark.asyncio
async def test_schulleitung_cannot_stage_teachers(as_schulleitung_a: AsyncClient) -> None:
    csv = f"{TEACHERS_HEADER}\nErika,Lehrer,,erika.lehrer@schule.ch,,true\n"
    r = await as_schulleitung_a.post(
        "/imports?kind=teachers", files={"file": ("t.csv", csv, "text/csv")}
    )
    assert r.status_code == 403, r.text


@pytest.mark.asyncio
async def test_schulleitung_cannot_stage_students(
    as_schulleitung_a: AsyncClient, db_session: AsyncSession, school_a: int
) -> None:
    await _seed_class(db_session, school_a, "3a", 3)
    csv = f"{STUDENTS_HEADER}\nAnna,Muster,,anna.muster@schule.ch,,3a,2026-08-12,true\n"
    r = await as_schulleitung_a.post(
        "/imports?kind=students",
        files={"file": ("students.csv", csv, "text/csv")},
    )
    assert r.status_code == 403, r.text


@pytest.mark.asyncio
async def test_smi_can_stage_students(
    as_smi_a: AsyncClient, db_session: AsyncSession, school_a: int
) -> None:
    await _seed_class(db_session, school_a, "3a", 3)
    csv = f"{STUDENTS_HEADER}\nAnna,Muster,,anna.muster@schule.ch,,3a,2026-08-12,true\n"
    r = await as_smi_a.post(
        "/imports?kind=students",
        files={"file": ("students.csv", csv, "text/csv")},
    )
    assert r.status_code == 201, r.text
    assert r.json()["counts"]["create"] == 1


@pytest.mark.asyncio
async def test_schulleitung_can_still_stage_classes(
    as_schulleitung_a: AsyncClient,
) -> None:
    csv = "name,kuerzel,jahrgangsstufe\n9z,9z,9\n"
    r = await as_schulleitung_a.post(
        "/imports?kind=classes",
        files={"file": ("classes.csv", csv, "text/csv")},
    )
    assert r.status_code == 201, r.text


@pytest.mark.asyncio
async def test_schulleitung_cannot_download_handouts(as_schulleitung_a: AsyncClient) -> None:
    body = {
        "credentials": [
            {
                "upn": "a@schule.ch",
                "display_name": "A",
                "class_name": "3a",
                "password": "Tiger-Wolke-47",
                "force_change": True,
            }
        ],
    }
    r = await as_schulleitung_a.post("/imports/handouts", json=body)
    assert r.status_code == 403, r.text


@pytest.mark.asyncio
async def test_render_handouts_zip(as_smi_a: AsyncClient) -> None:
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
    r = await as_smi_a.post("/imports/handouts", json=body)
    assert r.status_code == 200, r.text
    assert r.headers["content-type"] == "application/zip"
    zf = zipfile.ZipFile(io.BytesIO(r.content))
    assert set(zf.namelist()) == {"schueler-handouts.pdf", "klassen-uebersicht.pdf"}
    for name in zf.namelist():
        assert zf.read(name)[:4] == b"%PDF"


@pytest.mark.asyncio
async def test_handouts_empty_400(as_smi_a: AsyncClient) -> None:
    r = await as_smi_a.post("/imports/handouts", json={"credentials": []})
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_stage_error_when_ou_not_configured(
    as_smi_a: AsyncClient, db_session: AsyncSession, school_a: int
) -> None:
    # Clear the "other" OU on the school so a Zyklus-1/2 class cannot be provisioned.
    for school in (await db_session.execute(select(School))).scalars().all():
        school.ad_ou_students_other = None
    await db_session.commit()
    await _seed_class(db_session, school_a, "3a", 3)

    csv = f"{STUDENTS_HEADER}\nAnna,Muster,,anna.muster@schule.ch,,3a,2026-08-12,true\n"
    r = await as_smi_a.post(
        "/imports?kind=students",
        files={"file": ("students.csv", csv, "text/csv")},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["counts"]["error"] == 1
    assert "OU" in " ".join(body["rows"][0]["errors"])


@pytest.mark.asyncio
async def test_stage_error_when_upn_exists(
    as_smi_a: AsyncClient, db_session: AsyncSession, school_a: int
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
    r = await as_smi_a.post(
        "/imports?kind=students",
        files={"file": ("students.csv", csv, "text/csv")},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["counts"]["error"] == 1
    assert "already exists" in " ".join(body["rows"][0]["errors"])
