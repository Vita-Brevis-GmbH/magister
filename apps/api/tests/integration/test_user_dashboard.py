"""GET /users/{guid}/dashboard — active classes + their Klassenlehrer."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from magister_api.models.auth import AdUserCache
from magister_api.models.class_membership import ClassMembership
from magister_api.models.class_teacher_role import ClassTeacherRole
from magister_api.models.school_class import CLASS_STATUS_ACTIVE, SchoolClass

pytestmark = pytest.mark.postgres

STUDENT_GUID = "00000000-0000-0000-0000-0000000000e1"
TEACHER_GUID = "00000000-0000-0000-0000-0000000000e2"


async def _seed_user(
    session: AsyncSession, *, guid: str, school_id: int, upn: str, kind: str, display_name: str
) -> None:
    session.add(
        AdUserCache(
            ad_object_guid=guid,
            school_id=school_id,
            upn=upn,
            given_name=None,
            surname=None,
            display_name=display_name,
            kind=kind,
            enabled=True,
            last_sync_at=None,
            ms_ds_consistency_guid=guid,
        )
    )


@pytest.mark.asyncio
async def test_dashboard_lists_classes_and_teachers(
    as_admin: AsyncClient, db_session: AsyncSession, school_a: int
) -> None:
    now = datetime.now(UTC)
    await _seed_user(
        db_session,
        guid=STUDENT_GUID,
        school_id=school_a,
        upn="kid@a.ch",
        kind="student",
        display_name="Kid",
    )
    await _seed_user(
        db_session,
        guid=TEACHER_GUID,
        school_id=school_a,
        upn="kl@a.ch",
        kind="teacher",
        display_name="Frau Lehrer",
    )
    cls = SchoolClass(
        school_id=school_a, name="3a", kuerzel="3A", jahrgangsstufe=3, status=CLASS_STATUS_ACTIVE
    )
    db_session.add(cls)
    await db_session.flush()
    db_session.add(
        ClassMembership(
            class_id=cls.id,
            ad_object_guid=STUDENT_GUID,
            valid_from=now - timedelta(days=1),
            valid_to=None,
        )
    )
    db_session.add(
        ClassTeacherRole(
            class_id=cls.id,
            ad_object_guid=TEACHER_GUID,
            role="haupt",
            valid_from=now - timedelta(days=1),
            valid_to=None,
        )
    )
    await db_session.commit()

    r = await as_admin.get(f"/users/{STUDENT_GUID}/dashboard")
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body["classes"]) == 1
    klass = body["classes"][0]
    assert klass["class_id"] == cls.id
    assert klass["name"] == "3a"
    assert [tch["upn"] for tch in klass["teachers"]] == ["kl@a.ch"]
    assert klass["teachers"][0]["role"] == "haupt"
    assert klass["teachers"][0]["display_name"] == "Frau Lehrer"


@pytest.mark.asyncio
async def test_dashboard_empty_for_user_without_classes(
    as_admin: AsyncClient, db_session: AsyncSession, school_a: int
) -> None:
    await _seed_user(
        db_session,
        guid=STUDENT_GUID,
        school_id=school_a,
        upn="kid@a.ch",
        kind="student",
        display_name="Kid",
    )
    await db_session.commit()

    r = await as_admin.get(f"/users/{STUDENT_GUID}/dashboard")
    assert r.status_code == 200
    assert r.json() == {"classes": []}


@pytest.mark.asyncio
async def test_dashboard_cross_school_404(
    as_schulleitung_b: AsyncClient, db_session: AsyncSession, school_a: int
) -> None:
    # Schulleitung B has no user-edit surface and the student is in school A.
    await _seed_user(
        db_session,
        guid=STUDENT_GUID,
        school_id=school_a,
        upn="kid@a.ch",
        kind="student",
        display_name="Kid",
    )
    await db_session.commit()

    r = await as_schulleitung_b.get(f"/users/{STUDENT_GUID}/dashboard")
    assert r.status_code == 404
