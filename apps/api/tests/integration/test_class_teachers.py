"""End-to-end /classes/{id}/teachers — DoD coverage for issue #5."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from magister_api.config import Settings
from magister_api.models.audit import AuditEvent
from magister_api.models.class_teacher_role import ClassTeacherRole
from magister_api.services.class_teachers import ClassTeacherService

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.postgres


KL_GUID_ANNA = "00000000-0000-0000-0000-0000000000a1"
KL_GUID_BENO = "00000000-0000-0000-0000-0000000000b2"
KL_GUID_CARL = "00000000-0000-0000-0000-0000000000c3"


def _iso(dt: datetime) -> str:
    return dt.isoformat()


async def _create_class_a(client: AsyncClient, name: str = "4a") -> int:
    r = await client.post("/classes", json={"name": name, "jahrgangsstufe": 4})
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def _audit_actions(engine: AsyncEngine) -> list[str]:
    sm = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
    async with sm() as s:
        return list(
            (await s.execute(select(AuditEvent.action).order_by(AuditEvent.id))).scalars().all()
        )


class TestAssignAndList:
    @pytest.mark.asyncio
    async def test_assign_haupt_then_list(
        self, as_schulleitung_a: AsyncClient, engine: AsyncEngine
    ) -> None:
        cid = await _create_class_a(as_schulleitung_a)
        now = datetime.now(UTC)
        r = await as_schulleitung_a.post(
            f"/classes/{cid}/teachers",
            json={
                "ad_object_guid": KL_GUID_ANNA,
                "role": "haupt",
                "valid_from": _iso(now),
            },
        )
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["class_id"] == cid
        assert body["role"] == "haupt"

        r = await as_schulleitung_a.get(f"/classes/{cid}/teachers")
        assert r.status_code == 200
        assert [t["ad_object_guid"] for t in r.json()] == [KL_GUID_ANNA]

        actions = await _audit_actions(engine)
        assert "class_teacher_assigned" in actions


class TestCoKlBothActive:
    @pytest.mark.asyncio
    async def test_two_active_kl_at_same_time(self, as_schulleitung_a: AsyncClient) -> None:
        cid = await _create_class_a(as_schulleitung_a)
        now = datetime.now(UTC)
        for guid, role in [(KL_GUID_ANNA, "haupt"), (KL_GUID_BENO, "co")]:
            r = await as_schulleitung_a.post(
                f"/classes/{cid}/teachers",
                json={
                    "ad_object_guid": guid,
                    "role": role,
                    "valid_from": _iso(now),
                },
            )
            assert r.status_code == 201, r.text

        r = await as_schulleitung_a.get(f"/classes/{cid}/teachers")
        assert r.status_code == 200
        assert {t["ad_object_guid"] for t in r.json()} == {KL_GUID_ANNA, KL_GUID_BENO}


class TestStellvertretungWindow:
    @pytest.mark.asyncio
    async def test_active_only_inside_window(
        self,
        as_schulleitung_a: AsyncClient,
        app_settings: Settings,
        db_session: AsyncSession,
    ) -> None:
        cid = await _create_class_a(as_schulleitung_a)
        # Window: yesterday → tomorrow
        now = datetime.now(UTC)
        valid_from = now - timedelta(days=1)
        valid_to = now + timedelta(days=1)
        r = await as_schulleitung_a.post(
            f"/classes/{cid}/teachers",
            json={
                "ad_object_guid": KL_GUID_CARL,
                "role": "stellvertretung",
                "valid_from": _iso(valid_from),
                "valid_to": _iso(valid_to),
            },
        )
        assert r.status_code == 201, r.text

        # Service-level helper: KL right now? Yes.
        from magister_api.repositories.base import ScopeContext

        scope = ScopeContext(ad_object_guid="x", upn="x@x.ch", is_admin=True)
        svc = ClassTeacherService(db_session, app_settings, scope)
        assert await svc.is_active_kl_of(ad_object_guid=KL_GUID_CARL, class_id=cid, now=now)
        # Before the window → not KL.
        assert not await svc.is_active_kl_of(
            ad_object_guid=KL_GUID_CARL,
            class_id=cid,
            now=valid_from - timedelta(seconds=1),
        )
        # After valid_to → not KL.
        assert not await svc.is_active_kl_of(
            ad_object_guid=KL_GUID_CARL,
            class_id=cid,
            now=valid_to + timedelta(seconds=1),
        )


class TestRevoke:
    @pytest.mark.asyncio
    async def test_revoke_clamps_valid_to(
        self,
        as_schulleitung_a: AsyncClient,
        engine: AsyncEngine,
    ) -> None:
        cid = await _create_class_a(as_schulleitung_a)
        now = datetime.now(UTC)
        r = await as_schulleitung_a.post(
            f"/classes/{cid}/teachers",
            json={
                "ad_object_guid": KL_GUID_ANNA,
                "role": "haupt",
                "valid_from": _iso(now),
            },
        )
        rid = r.json()["id"]

        r = await as_schulleitung_a.delete(f"/classes/{cid}/teachers/{rid}")
        assert r.status_code == 204

        # Row still exists with valid_to set to ~now (soft-delete).
        sm = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
        async with sm() as s:
            row = await s.get(ClassTeacherRole, rid)
            assert row is not None
            assert row.valid_to is not None

        actions = await _audit_actions(engine)
        assert "class_teacher_assigned" in actions
        assert "class_teacher_revoked" in actions

    @pytest.mark.asyncio
    async def test_revoke_unknown_role_id_404(self, as_schulleitung_a: AsyncClient) -> None:
        cid = await _create_class_a(as_schulleitung_a)
        r = await as_schulleitung_a.delete(f"/classes/{cid}/teachers/9999")
        assert r.status_code == 404


class TestCrossSchoolBlocked:
    @pytest.mark.asyncio
    async def test_schulleitung_a_cannot_assign_to_school_b_class(
        self,
        as_schulleitung_a: AsyncClient,
        as_schulleitung_b: AsyncClient,
    ) -> None:
        # B creates a class in school B.
        cid_b = await _create_class_a(as_schulleitung_b, name="5b")
        # A tries to assign a KL to it → 404 (scope hides it; we don't leak existence).
        r = await as_schulleitung_a.post(
            f"/classes/{cid_b}/teachers",
            json={
                "ad_object_guid": KL_GUID_ANNA,
                "role": "haupt",
                "valid_from": _iso(datetime.now(UTC)),
            },
        )
        assert r.status_code == 404
        assert r.json()["detail"] == "class_not_found"

    @pytest.mark.asyncio
    async def test_schulleitung_a_cannot_list_school_b_class(
        self,
        as_schulleitung_a: AsyncClient,
        as_schulleitung_b: AsyncClient,
    ) -> None:
        cid_b = await _create_class_a(as_schulleitung_b, name="5b")
        r = await as_schulleitung_a.get(f"/classes/{cid_b}/teachers")
        assert r.status_code == 404
