"""Fachlehrer (subject teacher): assignment, /me/students, and PW-reset RBAC."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from magister_api.ad.client import AdClient
from magister_api.config import Settings
from magister_api.models.auth import AdUserCache
from magister_api.models.class_membership import ClassMembership
from magister_api.models.school_class import CLASS_STATUS_ACTIVE, SchoolClass
from magister_api.models.subject_teacher_role import SubjectTeacherRole
from magister_api.routers.admin_sync import get_ad_client
from tests.integration._helpers import seed_user_with_session

pytestmark = pytest.mark.postgres

FL_GUID = "00000000-0000-0000-0000-0000000000fa"
STUDENT_GUID = "00000000-0000-0000-0000-000000fa0001"
STRANGER_GUID = "00000000-0000-0000-0000-000000fa0002"


def _le(g: str) -> bytes:
    return uuid.UUID(g).bytes_le


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


@pytest_asyncio.fixture
async def mock_ad(app_settings: Settings):
    settings = app_settings.model_copy(
        update={"ad_use_mock": True, "ad_users_search_base": "DC=schule,DC=local"}
    )
    client = AdClient(settings)
    conn = client.mock_connection()
    conn.strategy.add_entry(
        "CN=Stud,OU=Students,DC=schule,DC=local",
        {
            "objectClass": ["user"],
            "objectGUID": _le(STUDENT_GUID),
            "userPrincipalName": "stud@example.ch",
            "userAccountControl": 0x200,
        },
    )
    yield client
    await client.aclose()


async def _fl_client(
    app: FastAPI, app_settings: Settings, db_session: AsyncSession, school_id: int
) -> AsyncClient:
    """A plain teacher session (no schulleitung/SMI role) for the Fachlehrer."""
    sid, csrf = await seed_user_with_session(
        session=db_session,
        settings=app_settings,
        upn="fl@example.ch",
        ad_object_guid=FL_GUID,
        school_id=school_id,
        kind="teacher",
        role=None,
    )
    await db_session.commit()
    return AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
        cookies={"magister_session": sid, "magister_csrf": csrf},
        headers={"X-CSRF-Token": csrf},
    )


async def _class_with_subject_teacher_and_student(
    db_session: AsyncSession, *, school_id: int, student_guid: str = STUDENT_GUID
) -> int:
    now = datetime.now(UTC)
    cls = SchoolClass(
        school_id=school_id, name="3a", kuerzel="3A", jahrgangsstufe=3, status=CLASS_STATUS_ACTIVE
    )
    db_session.add(cls)
    await db_session.flush()
    db_session.add(
        SubjectTeacherRole(
            class_id=cls.id,
            ad_object_guid=FL_GUID,
            subject="Mathematik",
            valid_from=now - timedelta(days=1),
            valid_to=None,
        )
    )
    db_session.add(
        ClassMembership(
            class_id=cls.id,
            ad_object_guid=student_guid,
            valid_from=now - timedelta(days=1),
            valid_to=None,
        )
    )
    await db_session.commit()
    return cls.id


class TestAssignList:
    @pytest.mark.asyncio
    async def test_assign_then_list_shows_subject_and_label(
        self, as_schulleitung_a: AsyncClient, db_session: AsyncSession, school_a: int
    ) -> None:
        await _seed_user(
            db_session, guid=FL_GUID, school_id=school_a, upn="fl@example.ch", kind="teacher"
        )
        await db_session.commit()
        r = await as_schulleitung_a.post("/classes", json={"name": "3a", "jahrgangsstufe": 3})
        cid = r.json()["id"]

        r = await as_schulleitung_a.post(
            f"/classes/{cid}/subject-teachers",
            json={
                "ad_object_guid": FL_GUID,
                "subject": "Mathematik",
                "valid_from": datetime.now(UTC).isoformat(),
            },
        )
        assert r.status_code == 201, r.text
        assert r.json()["subject"] == "Mathematik"

        r = await as_schulleitung_a.get(f"/classes/{cid}/subject-teachers")
        assert r.status_code == 200
        rows = r.json()
        assert len(rows) == 1
        assert rows[0]["subject"] == "Mathematik"
        assert rows[0]["upn"] == "fl@example.ch"  # enriched from ad_user_cache


class TestMyStudents:
    @pytest.mark.asyncio
    async def test_fachlehrer_sees_their_students(
        self, app: FastAPI, app_settings: Settings, db_session: AsyncSession, school_a: int
    ) -> None:
        cid = await _class_with_subject_teacher_and_student(db_session, school_id=school_a)
        await _seed_user(
            db_session, guid=STUDENT_GUID, school_id=school_a, upn="stud@example.ch", kind="student"
        )
        await db_session.commit()

        fl = await _fl_client(app, app_settings, db_session, school_a)
        async with fl:
            r = await fl.get("/me/students")
        assert r.status_code == 200, r.text
        classes = r.json()["classes"]
        assert len(classes) == 1
        assert classes[0]["class_id"] == cid
        assert [s["ad_object_guid"] for s in classes[0]["students"]] == [STUDENT_GUID]


class TestPasswordResetRbac:
    @pytest.mark.asyncio
    async def test_fachlehrer_may_reset_own_student(
        self,
        app: FastAPI,
        app_settings: Settings,
        db_session: AsyncSession,
        school_a: int,
        mock_ad: AdClient,
    ) -> None:
        await _class_with_subject_teacher_and_student(db_session, school_id=school_a)
        await _seed_user(
            db_session, guid=STUDENT_GUID, school_id=school_a, upn="stud@example.ch", kind="student"
        )
        await db_session.commit()

        app.dependency_overrides[get_ad_client] = lambda: mock_ad
        try:
            fl = await _fl_client(app, app_settings, db_session, school_a)
            async with fl:
                r = await fl.post(
                    f"/students/{STUDENT_GUID}/password-reset", json={"mode": "generate"}
                )
            assert r.status_code == 200, r.text
        finally:
            app.dependency_overrides.pop(get_ad_client, None)

    @pytest.mark.asyncio
    async def test_fachlehrer_cannot_reset_stranger(
        self,
        app: FastAPI,
        app_settings: Settings,
        db_session: AsyncSession,
        school_a: int,
        mock_ad: AdClient,
    ) -> None:
        await _class_with_subject_teacher_and_student(db_session, school_id=school_a)
        # A student the Fachlehrer does NOT teach.
        await _seed_user(
            db_session,
            guid=STRANGER_GUID,
            school_id=school_a,
            upn="stranger@example.ch",
            kind="student",
        )
        await db_session.commit()

        app.dependency_overrides[get_ad_client] = lambda: mock_ad
        try:
            fl = await _fl_client(app, app_settings, db_session, school_a)
            async with fl:
                r = await fl.post(
                    f"/students/{STRANGER_GUID}/password-reset", json={"mode": "generate"}
                )
            assert r.status_code == 404
        finally:
            app.dependency_overrides.pop(get_ad_client, None)
