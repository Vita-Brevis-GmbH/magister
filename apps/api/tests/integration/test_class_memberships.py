"""End-to-end ``/classes/{id}/students`` — DoD coverage for issue #6."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from magister_api.config import Settings
from magister_api.models.audit import AuditEvent
from magister_api.models.class_membership import ClassMembership
from tests.integration._helpers import seed_user_with_session

if TYPE_CHECKING:
    from fastapi import FastAPI
    from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.postgres

STUDENT_GUID = "00000000-0000-0000-0000-0000000000aa"
OTHER_STUDENT_GUID = "00000000-0000-0000-0000-0000000000bb"
KL_GUID = "00000000-0000-0000-0000-0000000000cc"


def _iso(dt: datetime) -> str:
    return dt.isoformat()


async def _create_class(client: AsyncClient, name: str = "4a") -> int:
    r = await client.post("/classes", json={"name": name, "jahrgangsstufe": 4})
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def _audit_actions(engine: AsyncEngine) -> list[str]:
    sm = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
    async with sm() as s:
        return list(
            (await s.execute(select(AuditEvent.action).order_by(AuditEvent.id))).scalars().all()
        )


class TestSchulleitungAddListRemove:
    @pytest.mark.asyncio
    async def test_full_cycle(
        self,
        as_schulleitung_a: AsyncClient,
        engine: AsyncEngine,
    ) -> None:
        cid = await _create_class(as_schulleitung_a)
        r = await as_schulleitung_a.post(
            f"/classes/{cid}/students",
            json={"ad_object_guid": STUDENT_GUID},
        )
        assert r.status_code == 201, r.text
        body = r.json()
        mid = body["id"]
        assert body["class_id"] == cid
        assert body["ad_object_guid"] == STUDENT_GUID
        assert body["valid_to"] is None

        # Listing returns the active row.
        r = await as_schulleitung_a.get(f"/classes/{cid}/students")
        assert r.status_code == 200
        assert [m["ad_object_guid"] for m in r.json()] == [STUDENT_GUID]

        # Remove → 204; row remains in DB with valid_to set.
        r = await as_schulleitung_a.delete(f"/classes/{cid}/students/{mid}")
        assert r.status_code == 204
        sm = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
        async with sm() as s:
            row = await s.get(ClassMembership, mid)
            assert row is not None
            assert row.valid_to is not None

        # And no longer in the active list.
        r = await as_schulleitung_a.get(f"/classes/{cid}/students")
        assert r.json() == []

        actions = await _audit_actions(engine)
        assert "student_added_to_class" in actions
        assert "student_removed_from_class" in actions

    @pytest.mark.asyncio
    async def test_future_dated_membership_shows_on_roster(
        self, as_schulleitung_a: AsyncClient
    ) -> None:
        # A student assigned now but starting later (e.g. imported before the
        # school year) must still appear on the class roster.
        cid = await _create_class(as_schulleitung_a, name="5a")
        future = datetime.now(UTC) + timedelta(days=30)
        r = await as_schulleitung_a.post(
            f"/classes/{cid}/students",
            json={"ad_object_guid": STUDENT_GUID, "valid_from": _iso(future)},
        )
        assert r.status_code == 201, r.text

        r = await as_schulleitung_a.get(f"/classes/{cid}/students")
        assert r.status_code == 200
        assert [m["ad_object_guid"] for m in r.json()] == [STUDENT_GUID]

    @pytest.mark.asyncio
    async def test_remove_unknown_membership_404(self, as_schulleitung_a: AsyncClient) -> None:
        cid = await _create_class(as_schulleitung_a)
        r = await as_schulleitung_a.delete(f"/classes/{cid}/students/9999")
        assert r.status_code == 404


class TestMidYearSwitch:
    @pytest.mark.asyncio
    async def test_old_membership_closed_new_active(
        self,
        as_schulleitung_a: AsyncClient,
        engine: AsyncEngine,
    ) -> None:
        cid_a = await _create_class(as_schulleitung_a, name="3a")
        cid_b = await _create_class(as_schulleitung_a, name="4a")

        # 1) Add to class 3a, far in the past so it's clearly active "before" the switch.
        old_from = datetime.now(UTC) - timedelta(days=120)
        r = await as_schulleitung_a.post(
            f"/classes/{cid_a}/students",
            json={"ad_object_guid": STUDENT_GUID, "valid_from": _iso(old_from)},
        )
        assert r.status_code == 201, r.text
        old_id = r.json()["id"]

        # 2) Mid-year switch: add to class 4a now. The previous one should auto-close.
        r = await as_schulleitung_a.post(
            f"/classes/{cid_b}/students",
            json={"ad_object_guid": STUDENT_GUID},
        )
        assert r.status_code == 201, r.text
        new_id = r.json()["id"]
        assert new_id != old_id

        # Old row still exists, but valid_to was clamped.
        sm = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
        async with sm() as s:
            old_row = await s.get(ClassMembership, old_id)
            new_row = await s.get(ClassMembership, new_id)
        assert old_row is not None
        assert old_row.valid_to is not None
        assert new_row is not None
        assert new_row.valid_to is None
        assert old_row.valid_to < new_row.valid_from

        # Class 3a active list is empty; class 4a has the student.
        r = await as_schulleitung_a.get(f"/classes/{cid_a}/students")
        assert r.json() == []
        r = await as_schulleitung_a.get(f"/classes/{cid_b}/students")
        assert [m["ad_object_guid"] for m in r.json()] == [STUDENT_GUID]


class TestOverlapRejected:
    @pytest.mark.asyncio
    async def test_same_class_overlap_409(self, as_schulleitung_a: AsyncClient) -> None:
        cid = await _create_class(as_schulleitung_a)
        now = datetime.now(UTC)
        r = await as_schulleitung_a.post(
            f"/classes/{cid}/students",
            json={
                "ad_object_guid": STUDENT_GUID,
                "valid_from": _iso(now - timedelta(days=10)),
                "valid_to": _iso(now + timedelta(days=10)),
            },
        )
        assert r.status_code == 201, r.text

        # Second overlapping membership for the same student in the same class.
        r = await as_schulleitung_a.post(
            f"/classes/{cid}/students",
            json={
                "ad_object_guid": STUDENT_GUID,
                "valid_from": _iso(now),
                "valid_to": _iso(now + timedelta(days=20)),
            },
        )
        assert r.status_code == 409
        assert r.json()["detail"] == "overlapping_membership"


class TestCrossSchoolBlocked:
    @pytest.mark.asyncio
    async def test_kl_a_cannot_assign_to_class_b(
        self,
        as_schulleitung_a: AsyncClient,
        as_schulleitung_b: AsyncClient,
    ) -> None:
        cid_b = await _create_class(as_schulleitung_b, name="5b")
        r = await as_schulleitung_a.post(
            f"/classes/{cid_b}/students",
            json={"ad_object_guid": STUDENT_GUID},
        )
        # 404 (scope hides the class) — never 403, to avoid leaking existence.
        assert r.status_code == 404
        assert r.json()["detail"] == "class_not_found"


class TestKlOfClassCanMutate:
    @pytest.mark.asyncio
    async def test_active_kl_can_add_and_remove_students(
        self,
        as_schulleitung_a: AsyncClient,
        app: FastAPI,
        app_settings: Settings,
        db_session: AsyncSession,
        school_a: int,
        engine: AsyncEngine,
    ) -> None:
        # 1) Schulleitung creates class A and assigns Anna as KL.
        cid = await _create_class(as_schulleitung_a)
        now = datetime.now(UTC)
        r = await as_schulleitung_a.post(
            f"/classes/{cid}/teachers",
            json={
                "ad_object_guid": KL_GUID,
                "role": "haupt",
                "valid_from": _iso(now - timedelta(seconds=1)),
            },
        )
        assert r.status_code == 201, r.text

        # 2) Seed Anna as a teacher session WITHOUT schulleitung role.
        sid, csrf = await seed_user_with_session(
            session=db_session,
            settings=app_settings,
            upn="kl-anna@example.ch",
            ad_object_guid=KL_GUID,
            school_id=school_a,
            kind="teacher",
            role=None,
            role_school_id=None,
        )
        await db_session.commit()
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://testserver",
            cookies={"magister_session": sid, "magister_csrf": csrf},
            headers={"X-CSRF-Token": csrf},
        ) as kl_client:
            # KL adds a student.
            r = await kl_client.post(
                f"/classes/{cid}/students",
                json={"ad_object_guid": STUDENT_GUID},
            )
            assert r.status_code == 201, r.text
            mid = r.json()["id"]

            # KL removes the student.
            r = await kl_client.delete(f"/classes/{cid}/students/{mid}")
            assert r.status_code == 204

        # Audit captured both actions with the KL as actor.
        sm = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
        async with sm() as s:
            actor_upns = list(
                (
                    await s.execute(
                        select(AuditEvent.actor_upn)
                        .where(AuditEvent.target_kind == "class_membership")
                        .order_by(AuditEvent.id)
                    )
                )
                .scalars()
                .all()
            )
        assert all(u == "kl-anna@example.ch" for u in actor_upns)

    @pytest.mark.asyncio
    async def test_random_teacher_blocked(
        self,
        as_schulleitung_a: AsyncClient,
        app: FastAPI,
        app_settings: Settings,
        db_session: AsyncSession,
        school_a: int,
    ) -> None:
        cid = await _create_class(as_schulleitung_a)
        # Plain teacher with no KL role and no schulleitung role.
        sid, csrf = await seed_user_with_session(
            session=db_session,
            settings=app_settings,
            upn="rando@example.ch",
            ad_object_guid="00000000-0000-0000-0000-0000000000ee",
            school_id=school_a,
            kind="teacher",
            role=None,
        )
        await db_session.commit()
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://testserver",
            cookies={"magister_session": sid, "magister_csrf": csrf},
            headers={"X-CSRF-Token": csrf},
        ) as rando:
            r = await rando.post(
                f"/classes/{cid}/students",
                json={"ad_object_guid": OTHER_STUDENT_GUID},
            )
            # Outsider without KL or Schulleitung gets 404 — we don't leak
            # that the class exists.
            assert r.status_code == 404
            assert r.json()["detail"] == "class_not_found"
