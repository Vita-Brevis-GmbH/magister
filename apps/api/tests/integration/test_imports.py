"""Integration tests for the CSV-Import endpoints (M3 US-2)."""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from magister_api.config import Settings
from magister_api.models.auth import AdUserCache
from magister_api.models.school_class import SchoolClass

# ---------------------------------------------------------------------------
# GET /imports/templates/{kind}.csv
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_template_classes_csv(as_schulleitung_a: AsyncClient) -> None:
    r = await as_schulleitung_a.get("/imports/templates/classes.csv")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/csv")
    assert 'filename="classes.csv"' in r.headers["content-disposition"]
    body = r.text
    lines = body.strip().splitlines()
    assert lines[0] == "name,kuerzel,jahrgangsstufe"
    assert len(lines) >= 4  # header + 3 example rows


@pytest.mark.asyncio
async def test_template_class_memberships_csv(as_schulleitung_a: AsyncClient) -> None:
    r = await as_schulleitung_a.get("/imports/templates/class_memberships.csv")
    assert r.status_code == 200
    assert r.text.splitlines()[0] == "student_upn,class_name,valid_from,valid_to"


@pytest.mark.asyncio
async def test_template_class_teachers_csv(as_schulleitung_a: AsyncClient) -> None:
    r = await as_schulleitung_a.get("/imports/templates/class_teachers.csv")
    assert r.status_code == 200
    assert r.text.splitlines()[0] == "teacher_upn,class_name,role,valid_from,valid_to"


@pytest.mark.asyncio
async def test_template_unknown_kind_404(as_schulleitung_a: AsyncClient) -> None:
    r = await as_schulleitung_a.get("/imports/templates/bogus.csv")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_template_requires_auth(client: AsyncClient) -> None:
    r = await client.get("/imports/templates/classes.csv")
    assert r.status_code == 401


# ---------------------------------------------------------------------------
# POST /imports  (stage)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_stage_classes_create_and_skip(
    as_schulleitung_a: AsyncClient, db_session: AsyncSession, school_a: int
) -> None:
    # Pre-seed one existing class.
    db_session.add(SchoolClass(school_id=school_a, name="3a", kuerzel="3a", jahrgangsstufe=3))
    await db_session.commit()

    csv = "name,kuerzel,jahrgangsstufe\n3a,3a,3\n3b,3b,3\n4a,,4\n"
    r = await as_schulleitung_a.post(
        "/imports?kind=classes",
        files={"file": ("classes.csv", csv, "text/csv")},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["kind"] == "classes"
    assert body["status"] == "staged"
    assert body["school_id"] == school_a
    assert body["counts"]["create"] == 2
    assert body["counts"]["skip"] == 1
    assert body["counts"]["error"] == 0


@pytest.mark.asyncio
async def test_stage_classes_invalid_header_400(as_schulleitung_a: AsyncClient) -> None:
    csv = "wrong,header,here\n3a,3a,3\n"
    r = await as_schulleitung_a.post(
        "/imports?kind=classes",
        files={"file": ("bad.csv", csv, "text/csv")},
    )
    assert r.status_code == 400
    assert "csv header" in r.json()["detail"]


@pytest.mark.asyncio
async def test_stage_unknown_kind_400(as_schulleitung_a: AsyncClient) -> None:
    csv = "a,b,c\n1,2,3\n"
    r = await as_schulleitung_a.post(
        "/imports?kind=bogus",
        files={"file": ("x.csv", csv, "text/csv")},
    )
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_stage_membership_missing_user_is_error(
    as_schulleitung_a: AsyncClient, db_session: AsyncSession, school_a: int
) -> None:
    db_session.add(SchoolClass(school_id=school_a, name="3a", kuerzel="3a", jahrgangsstufe=3))
    await db_session.commit()
    csv = "student_upn,class_name,valid_from,valid_to\nghost@example.ch,3a,2026-08-12,\n"
    r = await as_schulleitung_a.post(
        "/imports?kind=class_memberships",
        files={"file": ("m.csv", csv, "text/csv")},
    )
    assert r.status_code == 201
    body = r.json()
    assert body["counts"]["error"] == 1
    assert body["rows"][0]["action"] == "error"
    assert "ghost@example.ch" in body["rows"][0]["errors"][0]


@pytest.mark.asyncio
async def test_kl_forbidden_no_access(
    client: AsyncClient,
    db_session: AsyncSession,
    app_settings: Settings,
) -> None:
    from tests.integration._helpers import seed_user_with_session

    sid, csrf = await seed_user_with_session(
        session=db_session,
        settings=app_settings,
        upn="kl@example.ch",
        ad_object_guid="00000000-0000-0000-0000-0000000000ff",
        school_id=None,
        kind="teacher",
        role=None,
    )
    await db_session.commit()
    client.cookies.set("magister_session", sid)
    client.cookies.set("magister_csrf", csrf)
    client.headers["X-CSRF-Token"] = csrf
    r = await client.get("/imports/templates/classes.csv")
    assert r.status_code == 403


# ---------------------------------------------------------------------------
# Full stage → apply roundtrip
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_apply_creates_classes(
    as_schulleitung_a: AsyncClient, db_session: AsyncSession, school_a: int
) -> None:
    csv = "name,kuerzel,jahrgangsstufe\n5a,5a,5\n5b,5b,5\n"
    r = await as_schulleitung_a.post(
        "/imports?kind=classes",
        files={"file": ("classes.csv", csv, "text/csv")},
    )
    job_id = r.json()["id"]

    r2 = await as_schulleitung_a.post(f"/imports/{job_id}/apply")
    assert r2.status_code == 200, r2.text
    body = r2.json()
    assert body["status"] == "applied"
    assert body["summary"]["applied"] == {
        "created": 2,
        "updated": 0,
        "skipped": 0,
        "failed": 0,
    }

    # Verify the classes really exist.
    from sqlalchemy import select

    rows = (
        (
            await db_session.execute(
                select(SchoolClass)
                .where(SchoolClass.school_id == school_a)
                .order_by(SchoolClass.name)
            )
        )
        .scalars()
        .all()
    )
    assert [c.name for c in rows] == ["5a", "5b"]


@pytest.mark.asyncio
async def test_apply_membership_with_valid_user(
    as_schulleitung_a: AsyncClient, db_session: AsyncSession, school_a: int
) -> None:
    # Seed an AD user + class.
    db_session.add(SchoolClass(school_id=school_a, name="3a", kuerzel="3a", jahrgangsstufe=3))
    db_session.add(
        AdUserCache(
            ad_object_guid="00000000-0000-0000-0000-0000000000c1",
            school_id=school_a,
            upn="anna@example.ch",
            kind="student",
            enabled=True,
            ms_ds_consistency_guid="00000000-0000-0000-0000-0000000000c1",
        )
    )
    await db_session.commit()

    csv = "student_upn,class_name,valid_from,valid_to\nanna@example.ch,3a,2026-08-12,\n"
    r = await as_schulleitung_a.post(
        "/imports?kind=class_memberships",
        files={"file": ("m.csv", csv, "text/csv")},
    )
    assert r.status_code == 201, r.text
    job_id = r.json()["id"]

    r2 = await as_schulleitung_a.post(f"/imports/{job_id}/apply")
    assert r2.status_code == 200
    assert r2.json()["summary"]["applied"]["created"] == 1


@pytest.mark.asyncio
async def test_cannot_apply_twice(
    as_schulleitung_a: AsyncClient,
) -> None:
    csv = "name,kuerzel,jahrgangsstufe\n6a,6a,6\n"
    r = await as_schulleitung_a.post(
        "/imports?kind=classes",
        files={"file": ("classes.csv", csv, "text/csv")},
    )
    job_id = r.json()["id"]
    assert (await as_schulleitung_a.post(f"/imports/{job_id}/apply")).status_code == 200
    r2 = await as_schulleitung_a.post(f"/imports/{job_id}/apply")
    assert r2.status_code == 409


@pytest.mark.asyncio
async def test_cancel_marks_cancelled(
    as_schulleitung_a: AsyncClient,
) -> None:
    csv = "name,kuerzel,jahrgangsstufe\n7a,7a,7\n"
    r = await as_schulleitung_a.post(
        "/imports?kind=classes",
        files={"file": ("classes.csv", csv, "text/csv")},
    )
    job_id = r.json()["id"]
    r2 = await as_schulleitung_a.delete(f"/imports/{job_id}")
    assert r2.status_code == 204
    r3 = await as_schulleitung_a.get(f"/imports/{job_id}")
    assert r3.json()["status"] == "cancelled"


# ---------------------------------------------------------------------------
# Cross-school scope
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_other_school_cannot_see_job(
    as_schulleitung_a: AsyncClient,
    as_schulleitung_b: AsyncClient,
) -> None:
    csv = "name,kuerzel,jahrgangsstufe\n8a,8a,8\n"
    r = await as_schulleitung_a.post(
        "/imports?kind=classes",
        files={"file": ("classes.csv", csv, "text/csv")},
    )
    job_id = r.json()["id"]
    r2 = await as_schulleitung_b.get(f"/imports/{job_id}")
    assert r2.status_code == 404
