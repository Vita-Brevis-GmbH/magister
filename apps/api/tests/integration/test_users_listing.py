"""GET /users — listing with school-scope filter, attribute filters, pagination.

The scope filter is the security-critical part: a Schulleitung must only ever
see ad_user_cache rows from their own school(s); Admin sees everything.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from magister_api.config import Settings
from magister_api.models.auth import AdUserCache
from magister_api.models.class_membership import ClassMembership
from magister_api.models.class_teacher_role import ClassTeacherRole
from magister_api.models.school_class import CLASS_STATUS_ACTIVE, SchoolClass
from tests.integration._helpers import seed_user_with_session

pytestmark = pytest.mark.postgres


async def _seed_user(
    session: AsyncSession,
    *,
    guid: str,
    school_id: int | None,
    upn: str,
    kind: str = "teacher",
    enabled: bool = True,
    given_name: str | None = None,
    surname: str | None = None,
) -> None:
    session.add(
        AdUserCache(
            ad_object_guid=guid,
            school_id=school_id,
            upn=upn,
            given_name=given_name,
            surname=surname,
            display_name=None,
            kind=kind,
            enabled=enabled,
            last_sync_at=None,
            ms_ds_consistency_guid=guid,
        )
    )
    await session.commit()


def _upns(body: Any) -> set[str]:
    return {item["upn"] for item in body["items"]}


class TestScopeFilter:
    @pytest.mark.asyncio
    async def test_schulleitung_sees_only_own_school(
        self,
        as_schulleitung_a: AsyncClient,
        db_session: AsyncSession,
        school_a: int,
        school_b: int,
    ) -> None:
        await _seed_user(
            db_session,
            guid="aaa10000-0000-0000-0000-000000000001",
            school_id=school_a,
            upn="anna@a.ch",
        )
        await _seed_user(
            db_session,
            guid="bbb10000-0000-0000-0000-000000000001",
            school_id=school_b,
            upn="beat@b.ch",
        )

        r = await as_schulleitung_a.get("/users")
        assert r.status_code == 200, r.text
        body = r.json()
        assert "anna@a.ch" in _upns(body)
        assert "beat@b.ch" not in _upns(body)
        assert all(item["school_id"] == school_a for item in body["items"])

    @pytest.mark.asyncio
    async def test_admin_sees_all_schools(
        self,
        as_admin: AsyncClient,
        db_session: AsyncSession,
        school_a: int,
        school_b: int,
    ) -> None:
        await _seed_user(
            db_session,
            guid="aaa10000-0000-0000-0000-000000000001",
            school_id=school_a,
            upn="anna@a.ch",
        )
        await _seed_user(
            db_session,
            guid="bbb10000-0000-0000-0000-000000000001",
            school_id=school_b,
            upn="beat@b.ch",
        )

        r = await as_admin.get("/users")
        assert r.status_code == 200
        upns = _upns(r.json())
        assert {"anna@a.ch", "beat@b.ch"} <= upns

    @pytest.mark.asyncio
    async def test_plain_teacher_forbidden(
        self, app: FastAPI, app_settings: Settings, db_session: AsyncSession, school_a: int
    ) -> None:
        sid, csrf = await seed_user_with_session(
            session=db_session,
            settings=app_settings,
            upn="teacher@a.ch",
            ad_object_guid="ccc10000-0000-0000-0000-000000000001",
            school_id=school_a,
            kind="teacher",
            role=None,  # no schulleitung/smi grant
        )
        await db_session.commit()
        transport = ASGITransport(app=app)
        async with AsyncClient(
            transport=transport,
            base_url="http://testserver",
            cookies={"magister_session": sid, "magister_csrf": csrf},
            headers={"X-CSRF-Token": csrf},
        ) as c:
            r = await c.get("/users")
        assert r.status_code == 403


class TestFilters:
    @pytest.mark.asyncio
    async def test_kind_filter(
        self, as_schulleitung_a: AsyncClient, db_session: AsyncSession, school_a: int
    ) -> None:
        await _seed_user(
            db_session,
            guid="aaa10000-0000-0000-0000-000000000010",
            school_id=school_a,
            upn="pupil@a.ch",
            kind="student",
        )
        await _seed_user(
            db_session,
            guid="aaa10000-0000-0000-0000-000000000011",
            school_id=school_a,
            upn="prof@a.ch",
            kind="teacher",
        )

        r = await as_schulleitung_a.get("/users", params={"kind": "student"})
        assert r.status_code == 200
        assert all(item["kind"] == "student" for item in r.json()["items"])
        assert "pupil@a.ch" in _upns(r.json())

    @pytest.mark.asyncio
    async def test_enabled_filter(
        self, as_schulleitung_a: AsyncClient, db_session: AsyncSession, school_a: int
    ) -> None:
        await _seed_user(
            db_session,
            guid="aaa10000-0000-0000-0000-000000000020",
            school_id=school_a,
            upn="active@a.ch",
            enabled=True,
        )
        await _seed_user(
            db_session,
            guid="aaa10000-0000-0000-0000-000000000021",
            school_id=school_a,
            upn="locked@a.ch",
            enabled=False,
        )

        r = await as_schulleitung_a.get("/users", params={"enabled": "false"})
        assert r.status_code == 200
        assert _upns(r.json()) >= {"locked@a.ch"}
        assert all(item["enabled"] is False for item in r.json()["items"])

    @pytest.mark.asyncio
    async def test_search_filter(
        self, as_schulleitung_a: AsyncClient, db_session: AsyncSession, school_a: int
    ) -> None:
        await _seed_user(
            db_session,
            guid="aaa10000-0000-0000-0000-000000000030",
            school_id=school_a,
            upn="m@a.ch",
            surname="Müller",
        )
        await _seed_user(
            db_session,
            guid="aaa10000-0000-0000-0000-000000000031",
            school_id=school_a,
            upn="h@a.ch",
            surname="Huber",
        )

        r = await as_schulleitung_a.get("/users", params={"search": "müll"})
        assert r.status_code == 200
        assert _upns(r.json()) == {"m@a.ch"}


class TestClassFilter:
    @pytest.mark.asyncio
    async def test_class_id_filter_returns_students_and_teachers(
        self, as_schulleitung_a: AsyncClient, db_session: AsyncSession, school_a: int
    ) -> None:
        now = datetime.now(UTC)
        await _seed_user(
            db_session,
            guid="aaa10000-0000-0000-0000-0000000000s1",
            school_id=school_a,
            upn="pupil@a.ch",
            kind="student",
        )
        await _seed_user(
            db_session,
            guid="aaa10000-0000-0000-0000-0000000000t1",
            school_id=school_a,
            upn="teach@a.ch",
            kind="teacher",
        )
        await _seed_user(
            db_session,
            guid="aaa10000-0000-0000-0000-0000000000o1",
            school_id=school_a,
            upn="outsider@a.ch",
            kind="student",
        )
        cls = SchoolClass(
            school_id=school_a,
            name="2b",
            kuerzel="2B",
            jahrgangsstufe=2,
            status=CLASS_STATUS_ACTIVE,
        )
        db_session.add(cls)
        await db_session.flush()
        db_session.add(
            ClassMembership(
                class_id=cls.id,
                ad_object_guid="aaa10000-0000-0000-0000-0000000000s1",
                valid_from=now - timedelta(days=1),
                valid_to=None,
            )
        )
        db_session.add(
            ClassTeacherRole(
                class_id=cls.id,
                ad_object_guid="aaa10000-0000-0000-0000-0000000000t1",
                role="haupt",
                valid_from=now - timedelta(days=1),
                valid_to=None,
            )
        )
        await db_session.commit()

        r = await as_schulleitung_a.get("/users", params={"class_id": cls.id})
        assert r.status_code == 200, r.text
        upns = _upns(r.json())
        # Both the student and the teacher of the class show up; the outsider does not.
        assert upns == {"pupil@a.ch", "teach@a.ch"}


class TestPagination:
    @pytest.mark.asyncio
    async def test_offset_limit_and_total(
        self, as_schulleitung_a: AsyncClient, db_session: AsyncSession, school_a: int
    ) -> None:
        for i in range(3):
            await _seed_user(
                db_session,
                guid=f"aaa10000-0000-0000-0000-00000000004{i}",
                school_id=school_a,
                upn=f"u{i}@a.ch",
                surname=f"Sur{i}",
            )

        r = await as_schulleitung_a.get("/users", params={"limit": 2, "offset": 0})
        assert r.status_code == 200
        body = r.json()
        assert body["limit"] == 2
        assert body["offset"] == 0
        assert len(body["items"]) == 2
        # 3 seeded + the Schulleitung's own cached row = 4 in scope.
        assert body["total"] == 4
