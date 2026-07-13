"""End-to-end CRUD + assignment for /devices (Admin + SMI only)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from magister_api.models.audit import AuditEvent
from magister_api.models.auth import AdUserCache
from magister_api.models.school_class import SchoolClass

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.postgres


async def _actions(engine: AsyncEngine) -> list[str]:
    sm = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
    async with sm() as s:
        return list(
            (await s.execute(select(AuditEvent.action).order_by(AuditEvent.id))).scalars().all()
        )


class TestDeviceCrud:
    @pytest.mark.asyncio
    async def test_create_list_patch_delete(
        self, as_admin: AsyncClient, engine: AsyncEngine
    ) -> None:
        resp = await as_admin.post(
            "/devices",
            json={
                "name": "iPad-01",
                "device_type": "Tablet",
                "serial_number": "SN-123",
                "notes": "Koffer A",
            },
        )
        assert resp.status_code == 201, resp.text
        body = resp.json()
        did = body["id"]
        assert body["name"] == "iPad-01"
        assert body["source"] == "manual"
        assert body["school_id"] is None  # free pool on creation

        # List shows it.
        resp = await as_admin.get("/devices")
        assert resp.status_code == 200
        assert any(d["id"] == did for d in resp.json())

        # Patch attributes.
        resp = await as_admin.patch(f"/devices/{did}", json={"notes": "Koffer B"})
        assert resp.status_code == 200, resp.text
        assert resp.json()["notes"] == "Koffer B"

        # Delete.
        resp = await as_admin.delete(f"/devices/{did}")
        assert resp.status_code == 204
        resp = await as_admin.get(f"/devices/{did}")
        assert resp.status_code == 404

        actions = await _actions(engine)
        assert "device_created" in actions
        assert "device_updated" in actions
        assert "device_deleted" in actions

    @pytest.mark.asyncio
    async def test_schulleitung_forbidden(self, as_schulleitung_a: AsyncClient) -> None:
        resp = await as_schulleitung_a.get("/devices")
        assert resp.status_code == 403
        resp = await as_schulleitung_a.post("/devices", json={"name": "X"})
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_smi_can_manage(self, as_smi_a: AsyncClient) -> None:
        resp = await as_smi_a.post("/devices", json={"name": "SMI-Device"})
        assert resp.status_code == 201, resp.text
        resp = await as_smi_a.get("/devices")
        assert resp.status_code == 200
        assert any(d["name"] == "SMI-Device" for d in resp.json())


class TestDeviceAssignment:
    @pytest.mark.asyncio
    async def test_assign_to_school_then_free(
        self, as_admin: AsyncClient, school_a: int, engine: AsyncEngine
    ) -> None:
        did = (await as_admin.post("/devices", json={"name": "D1"})).json()["id"]

        resp = await as_admin.post(
            f"/devices/{did}/assign",
            json={"assignment_type": "school", "school_id": school_a},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["school_id"] == school_a
        assert resp.json()["class_id"] is None
        assert resp.json()["assigned_person_guid"] is None

        # Back to the free pool.
        resp = await as_admin.post(f"/devices/{did}/assign", json={"assignment_type": "free"})
        assert resp.status_code == 200
        assert resp.json()["school_id"] is None

        assert "device_assigned" in await _actions(engine)

    @pytest.mark.asyncio
    async def test_assign_to_class_derives_school(
        self, as_admin: AsyncClient, db_session: AsyncSession, school_a: int
    ) -> None:
        cls = SchoolClass(school_id=school_a, name="9z", jahrgangsstufe=9)
        db_session.add(cls)
        await db_session.flush()
        cid = cls.id
        await db_session.commit()

        did = (await as_admin.post("/devices", json={"name": "D2"})).json()["id"]
        resp = await as_admin.post(
            f"/devices/{did}/assign",
            json={"assignment_type": "class", "class_id": cid},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["class_id"] == cid
        assert resp.json()["school_id"] == school_a  # derived from the class

    @pytest.mark.asyncio
    async def test_assign_to_person_derives_school(
        self, as_admin: AsyncClient, db_session: AsyncSession, school_a: int
    ) -> None:
        guid = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
        db_session.add(
            AdUserCache(
                ad_object_guid=guid,
                school_id=school_a,
                upn="pupil@schule.ch",
                kind="student",
                enabled=True,
            )
        )
        await db_session.commit()

        did = (await as_admin.post("/devices", json={"name": "D3"})).json()["id"]
        resp = await as_admin.post(
            f"/devices/{did}/assign",
            json={"assignment_type": "person", "person_guid": guid},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["assigned_person_guid"] == guid
        assert resp.json()["school_id"] == school_a

    @pytest.mark.asyncio
    async def test_assign_person_requires_guid(self, as_admin: AsyncClient) -> None:
        did = (await as_admin.post("/devices", json={"name": "D4"})).json()["id"]
        resp = await as_admin.post(f"/devices/{did}/assign", json={"assignment_type": "person"})
        assert resp.status_code == 422
        assert resp.json()["detail"] == "person_guid_required"

    @pytest.mark.asyncio
    async def test_smi_cannot_bind_out_of_scope(self, as_smi_a: AsyncClient, school_b: int) -> None:
        did = (await as_smi_a.post("/devices", json={"name": "D5"})).json()["id"]
        resp = await as_smi_a.post(
            f"/devices/{did}/assign",
            json={"assignment_type": "school", "school_id": school_b},
        )
        assert resp.status_code == 403
        assert resp.json()["detail"] == "school_out_of_scope"


class TestDeviceScopeVisibility:
    @pytest.mark.asyncio
    async def test_smi_sees_free_pool_and_own_school_not_other(
        self,
        as_admin: AsyncClient,
        as_smi_a: AsyncClient,
        db_session: AsyncSession,
        school_a: int,
        school_b: int,
    ) -> None:
        # Free device (admin-created, unassigned).
        free_id = (await as_admin.post("/devices", json={"name": "Free"})).json()["id"]
        # Device bound to school B (out of SMI-A scope).
        b_id = (await as_admin.post("/devices", json={"name": "SchuleB"})).json()["id"]
        await as_admin.post(
            f"/devices/{b_id}/assign",
            json={"assignment_type": "school", "school_id": school_b},
        )

        resp = await as_smi_a.get("/devices")
        assert resp.status_code == 200
        ids = {d["id"] for d in resp.json()}
        assert free_id in ids  # free pool is visible
        assert b_id not in ids  # school B is not
