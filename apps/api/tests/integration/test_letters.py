"""Integration tests for parent-letter PDF generation (M3 US-1)."""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from magister_api.models.auth import AdUserCache
from magister_api.models.base import utcnow
from magister_api.models.class_membership import ClassMembership
from magister_api.models.school_class import SchoolClass


async def _seed_student(
    db: AsyncSession,
    *,
    school_id: int,
    upn: str = "anna@example.ch",
    display_name: str = "Anna Beispiel",
    guid_suffix: str = "01",
) -> tuple[str, int]:
    """Create a student with an active membership in a fresh class. Returns
    ``(student_guid, class_id)``."""
    cls = SchoolClass(school_id=school_id, name="3a", kuerzel="3a", jahrgangsstufe=3)
    db.add(cls)
    await db.flush()
    student = AdUserCache(
        ad_object_guid=f"00000000-0000-0000-0000-0000000000{guid_suffix}",
        school_id=school_id,
        upn=upn,
        display_name=display_name,
        kind="student",
        enabled=True,
        ms_ds_consistency_guid=f"00000000-0000-0000-0000-0000000000{guid_suffix}",
    )
    db.add(student)
    db.add(
        ClassMembership(
            class_id=cls.id,
            ad_object_guid=student.ad_object_guid,
            valid_from=utcnow(),
        )
    )
    await db.commit()
    return student.ad_object_guid, cls.id


@pytest.mark.asyncio
async def test_enrollment_pdf(
    as_schulleitung_a: AsyncClient,
    db_session: AsyncSession,
    school_a: int,
) -> None:
    student_guid, _ = await _seed_student(db_session, school_id=school_a)
    r = await as_schulleitung_a.post(
        "/letters/enrollment",
        json={
            "student_guid": student_guid,
            "school_year": "2026/27",
            "first_day": "12.08.2026",
        },
    )
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("application/pdf")
    assert r.content.startswith(b"%PDF-")
    assert len(r.content) > 1000


@pytest.mark.asyncio
async def test_class_change_pdf(
    as_schulleitung_a: AsyncClient,
    db_session: AsyncSession,
    school_a: int,
) -> None:
    student_guid, _ = await _seed_student(db_session, school_id=school_a)
    r = await as_schulleitung_a.post(
        "/letters/class_change",
        json={
            "student_guid": student_guid,
            "old_class_name": "2a",
            "effective_date": "01.11.2026",
        },
    )
    assert r.status_code == 200
    assert r.content.startswith(b"%PDF-")


@pytest.mark.asyncio
async def test_password_handout_pdf(
    as_schulleitung_a: AsyncClient,
    db_session: AsyncSession,
    school_a: int,
) -> None:
    student_guid, _ = await _seed_student(db_session, school_id=school_a)
    r = await as_schulleitung_a.post(
        "/letters/password_handout",
        json={"student_guid": student_guid, "temp_password": "Apfel-Berg-7"},
    )
    assert r.status_code == 200
    assert r.content.startswith(b"%PDF-")


@pytest.mark.asyncio
async def test_unknown_template_404(
    as_schulleitung_a: AsyncClient,
    db_session: AsyncSession,
    school_a: int,
) -> None:
    student_guid, _ = await _seed_student(db_session, school_id=school_a)
    r = await as_schulleitung_a.post(
        "/letters/bogus",
        json={"student_guid": student_guid},
    )
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_unknown_student_404(as_schulleitung_a: AsyncClient) -> None:
    r = await as_schulleitung_a.post(
        "/letters/enrollment",
        json={
            "student_guid": "00000000-0000-0000-0000-0000000000ff",
            "school_year": "2026/27",
            "first_day": "12.08.2026",
        },
    )
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_missing_required_fields_400(
    as_schulleitung_a: AsyncClient,
    db_session: AsyncSession,
    school_a: int,
) -> None:
    student_guid, _ = await _seed_student(db_session, school_id=school_a)
    r = await as_schulleitung_a.post(
        "/letters/password_handout",
        json={"student_guid": student_guid},  # missing temp_password
    )
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_cross_school_blocked(
    as_schulleitung_b: AsyncClient,
    db_session: AsyncSession,
    school_a: int,
) -> None:
    student_guid, _ = await _seed_student(db_session, school_id=school_a)
    r = await as_schulleitung_b.post(
        "/letters/enrollment",
        json={
            "student_guid": student_guid,
            "school_year": "2026/27",
            "first_day": "12.08.2026",
        },
    )
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_admin_can_print_for_any_school(
    as_admin: AsyncClient,
    db_session: AsyncSession,
    school_a: int,
) -> None:
    student_guid, _ = await _seed_student(db_session, school_id=school_a)
    r = await as_admin.post(
        "/letters/enrollment",
        json={
            "student_guid": student_guid,
            "school_year": "2026/27",
            "first_day": "12.08.2026",
        },
    )
    assert r.status_code == 200
