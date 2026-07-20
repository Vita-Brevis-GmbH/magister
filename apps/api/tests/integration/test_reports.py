"""Integration tests for the reporting endpoints (M3 US-3)."""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from magister_api.models.auth import AdUserCache
from magister_api.models.base import utcnow
from magister_api.models.class_membership import ClassMembership
from magister_api.models.class_teacher_role import ClassTeacherRole
from magister_api.models.school_class import SchoolClass


async def _seed_class_with_students(
    db: AsyncSession,
    *,
    school_id: int,
    class_name: str,
    jahrgang: int,
    student_count: int,
    guid_offset: int,
) -> int:
    cls = SchoolClass(
        school_id=school_id,
        name=class_name,
        kuerzel=class_name,
        jahrgangsstufe=jahrgang,
    )
    db.add(cls)
    await db.flush()
    for i in range(student_count):
        guid = f"00000000-0000-0000-0000-{guid_offset + i:012d}"
        db.add(
            AdUserCache(
                ad_object_guid=guid,
                school_id=school_id,
                upn=f"s{guid_offset + i}@example.ch",
                kind="student",
                enabled=True,
                ms_ds_consistency_guid=guid,
            )
        )
        db.add(
            ClassMembership(
                class_id=cls.id,
                ad_object_guid=guid,
                valid_from=utcnow(),
            )
        )
    await db.commit()
    return cls.id


# ---------------------------------------------------------------------------
# /reports/students-by-class
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_students_by_class_aggregates_scoped(
    as_schulleitung_a: AsyncClient,
    db_session: AsyncSession,
    school_a: int,
) -> None:
    await _seed_class_with_students(
        db_session,
        school_id=school_a,
        class_name="3a",
        jahrgang=3,
        student_count=5,
        guid_offset=100,
    )
    await _seed_class_with_students(
        db_session,
        school_id=school_a,
        class_name="3b",
        jahrgang=3,
        student_count=3,
        guid_offset=200,
    )

    r = await as_schulleitung_a.get("/reports/students-by-class")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total_students"] == 8
    assert body["total_classes"] == 2
    by_name = {row["name"]: row["student_count"] for row in body["rows"]}
    assert by_name == {"3a": 5, "3b": 3}


@pytest.mark.asyncio
async def test_students_by_class_other_school_excluded(
    as_schulleitung_a: AsyncClient,
    db_session: AsyncSession,
    school_a: int,
    school_b: int,
) -> None:
    await _seed_class_with_students(
        db_session,
        school_id=school_a,
        class_name="3a",
        jahrgang=3,
        student_count=4,
        guid_offset=300,
    )
    await _seed_class_with_students(
        db_session,
        school_id=school_b,
        class_name="9z",
        jahrgang=9,
        student_count=10,
        guid_offset=400,
    )

    r = await as_schulleitung_a.get("/reports/students-by-class")
    body = r.json()
    assert body["total_students"] == 4
    assert all(row["school_id"] == school_a for row in body["rows"])


@pytest.mark.asyncio
async def test_admin_sees_all_schools(
    as_admin: AsyncClient,
    db_session: AsyncSession,
    school_a: int,
    school_b: int,
) -> None:
    await _seed_class_with_students(
        db_session,
        school_id=school_a,
        class_name="3a",
        jahrgang=3,
        student_count=4,
        guid_offset=500,
    )
    await _seed_class_with_students(
        db_session,
        school_id=school_b,
        class_name="9z",
        jahrgang=9,
        student_count=10,
        guid_offset=600,
    )

    r = await as_admin.get("/reports/students-by-class")
    body = r.json()
    assert body["total_students"] == 14


@pytest.mark.asyncio
async def test_empty_class_counted_with_zero(
    as_schulleitung_a: AsyncClient,
    db_session: AsyncSession,
    school_a: int,
) -> None:
    db_session.add(SchoolClass(school_id=school_a, name="4a", kuerzel="4a", jahrgangsstufe=4))
    await db_session.commit()

    r = await as_schulleitung_a.get("/reports/students-by-class")
    body = r.json()
    assert body["total_classes"] == 1
    assert body["rows"][0]["student_count"] == 0


# ---------------------------------------------------------------------------
# /reports/students-by-school-year
# ---------------------------------------------------------------------------


async def _seed_students(
    db: AsyncSession,
    *,
    school_id: int,
    jahrgang: int | None,
    count: int,
    guid_offset: int,
) -> None:
    for i in range(count):
        guid = f"00000000-0000-0000-0000-{guid_offset + i:012d}"
        db.add(
            AdUserCache(
                ad_object_guid=guid,
                school_id=school_id,
                upn=f"y{guid_offset + i}@example.ch",
                kind="student",
                enabled=True,
                jahrgangsstufe=jahrgang,
                ms_ds_consistency_guid=guid,
            )
        )
    await db.commit()


@pytest.mark.asyncio
async def test_students_by_school_year_aggregates_scoped(
    as_schulleitung_a: AsyncClient,
    db_session: AsyncSession,
    school_a: int,
    school_b: int,
) -> None:
    await _seed_students(db_session, school_id=school_a, jahrgang=3, count=5, guid_offset=1000)
    await _seed_students(db_session, school_id=school_a, jahrgang=4, count=2, guid_offset=1100)
    await _seed_students(db_session, school_id=school_a, jahrgang=None, count=1, guid_offset=1200)
    # Other school is excluded for a Schulleitung scoped to A.
    await _seed_students(db_session, school_id=school_b, jahrgang=3, count=9, guid_offset=1300)

    r = await as_schulleitung_a.get("/reports/students-by-school-year")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total_students"] == 8
    by_year = {row["jahrgangsstufe"]: row["student_count"] for row in body["rows"]}
    assert by_year == {3: 5, 4: 2, None: 1}
    # Known years come first, the "unrecorded" (null) bucket sorts last.
    assert body["rows"][-1]["jahrgangsstufe"] is None


# ---------------------------------------------------------------------------
# /reports/teacher-workload
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_teacher_workload_role_breakdown(
    as_schulleitung_a: AsyncClient,
    db_session: AsyncSession,
    school_a: int,
) -> None:
    cls_id = await _seed_class_with_students(
        db_session,
        school_id=school_a,
        class_name="3a",
        jahrgang=3,
        student_count=0,
        guid_offset=700,
    )
    cls2_id = await _seed_class_with_students(
        db_session,
        school_id=school_a,
        class_name="3b",
        jahrgang=3,
        student_count=0,
        guid_offset=800,
    )
    teacher_guid = "00000000-0000-0000-0000-000000000aaa"
    db_session.add(
        AdUserCache(
            ad_object_guid=teacher_guid,
            school_id=school_a,
            upn="erika.lehrer@example.ch",
            display_name="Erika Lehrer",
            kind="teacher",
            enabled=True,
            ms_ds_consistency_guid=teacher_guid,
        )
    )
    db_session.add(
        ClassTeacherRole(
            class_id=cls_id,
            ad_object_guid=teacher_guid,
            role="haupt",
            valid_from=utcnow(),
        )
    )
    db_session.add(
        ClassTeacherRole(
            class_id=cls2_id,
            ad_object_guid=teacher_guid,
            role="co",
            valid_from=utcnow(),
        )
    )
    await db_session.commit()

    r = await as_schulleitung_a.get("/reports/teacher-workload")
    assert r.status_code == 200
    body = r.json()
    assert len(body["rows"]) == 1
    row = body["rows"][0]
    assert row["upn"] == "erika.lehrer@example.ch"
    assert row["haupt_count"] == 1
    assert row["co_count"] == 1
    assert row["stellvertretung_count"] == 0
    assert row["total"] == 2
    # "Lehrer-Klassen": the report lists which classes the teacher holds.
    assert row["classes"] == ["3a", "3b"]


@pytest.mark.asyncio
async def test_teacher_workload_excludes_archived_classes(
    as_schulleitung_a: AsyncClient,
    db_session: AsyncSession,
    school_a: int,
) -> None:
    cls = SchoolClass(
        school_id=school_a,
        name="9z",
        kuerzel="9z",
        jahrgangsstufe=9,
        status="archived",
    )
    db_session.add(cls)
    await db_session.flush()
    teacher_guid = "00000000-0000-0000-0000-000000000bbb"
    db_session.add(
        AdUserCache(
            ad_object_guid=teacher_guid,
            school_id=school_a,
            upn="alt@example.ch",
            kind="teacher",
            enabled=True,
            ms_ds_consistency_guid=teacher_guid,
        )
    )
    db_session.add(
        ClassTeacherRole(
            class_id=cls.id,
            ad_object_guid=teacher_guid,
            role="haupt",
            valid_from=utcnow(),
        )
    )
    await db_session.commit()

    r = await as_schulleitung_a.get("/reports/teacher-workload")
    assert r.json()["rows"] == []


# ---------------------------------------------------------------------------
# /reports/activity
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_activity_groups_audit_actions(
    as_schulleitung_a: AsyncClient,
    db_session: AsyncSession,
    school_a: int,
) -> None:
    # Stage one CSV (writes a real audit event), then read /activity.
    csv = "name,kuerzel,jahrgangsstufe\n5a,5a,5\n"
    await as_schulleitung_a.post(
        "/imports?kind=classes",
        files={"file": ("c.csv", csv, "text/csv")},
    )

    r = await as_schulleitung_a.get("/reports/activity?days=1")
    assert r.status_code == 200
    body = r.json()
    actions = {row["action"]: row["count"] for row in body["rows"]}
    assert actions.get("import_staged", 0) >= 1


@pytest.mark.asyncio
async def test_activity_days_param_validated(
    as_schulleitung_a: AsyncClient,
) -> None:
    r = await as_schulleitung_a.get("/reports/activity?days=0")
    assert r.status_code == 422
    r = await as_schulleitung_a.get("/reports/activity?days=400")
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_reports_require_schulleitung(client: AsyncClient) -> None:
    r = await client.get("/reports/students-by-class")
    assert r.status_code == 401
