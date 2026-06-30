"""Renaming / editing an entity must never break its relations.

Memberships and teacher roles join by class_id (PK) and ad_object_guid
(objectGUID) — both stable — so renaming a class or editing a user's label
must leave the links intact. This pins that guarantee down end-to-end.
"""

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

STUDENT_GUID = "00000000-0000-0000-0000-0000000000f1"
TEACHER_GUID = "00000000-0000-0000-0000-0000000000f2"


async def _seed_user(
    session: AsyncSession, *, guid: str, school_id: int, upn: str, kind: str
) -> None:
    session.add(
        AdUserCache(
            ad_object_guid=guid,
            school_id=school_id,
            upn=upn,
            given_name=None,
            surname=None,
            display_name=upn,
            kind=kind,
            enabled=True,
            last_sync_at=None,
            ms_ds_consistency_guid=guid,
        )
    )


@pytest.mark.asyncio
async def test_class_rename_keeps_students_and_teachers(
    as_schulleitung_a: AsyncClient, db_session: AsyncSession, school_a: int
) -> None:
    now = datetime.now(UTC)
    await _seed_user(
        db_session, guid=STUDENT_GUID, school_id=school_a, upn="kid@a.ch", kind="student"
    )
    await _seed_user(
        db_session, guid=TEACHER_GUID, school_id=school_a, upn="kl@a.ch", kind="teacher"
    )
    cls = SchoolClass(
        school_id=school_a, name="4a", kuerzel="4A", jahrgangsstufe=4, status=CLASS_STATUS_ACTIVE
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
    cid = cls.id

    # Rename name + kuerzel + details in one PATCH.
    r = await as_schulleitung_a.patch(
        f"/classes/{cid}", json={"name": "4a-neu", "kuerzel": "N4", "details": "Raum 7"}
    )
    assert r.status_code == 200, r.text
    assert r.json()["name"] == "4a-neu"

    # The student membership still resolves to this class…
    r = await as_schulleitung_a.get(f"/classes/{cid}/students")
    assert r.status_code == 200
    assert [s["ad_object_guid"] for s in r.json()] == [STUDENT_GUID]

    # …and so does the teacher role.
    r = await as_schulleitung_a.get(f"/classes/{cid}/teachers")
    assert r.status_code == 200
    assert [tch["ad_object_guid"] for tch in r.json()] == [TEACHER_GUID]


@pytest.mark.asyncio
async def test_class_rename_reflected_in_user_dashboard(
    as_admin: AsyncClient, db_session: AsyncSession, school_a: int
) -> None:
    now = datetime.now(UTC)
    await _seed_user(
        db_session, guid=STUDENT_GUID, school_id=school_a, upn="kid@a.ch", kind="student"
    )
    cls = SchoolClass(
        school_id=school_a, name="5a", kuerzel="5A", jahrgangsstufe=5, status=CLASS_STATUS_ACTIVE
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
    await db_session.commit()
    cid = cls.id

    r = await as_admin.patch(f"/classes/{cid}", json={"name": "5a-renamed"})
    assert r.status_code == 200

    # The dashboard join is by class_id, so the renamed class still appears.
    r = await as_admin.get(f"/users/{STUDENT_GUID}/dashboard")
    assert r.status_code == 200
    classes = r.json()["classes"]
    assert len(classes) == 1
    assert classes[0]["class_id"] == cid
    assert classes[0]["name"] == "5a-renamed"
