"""Device assignment history + freeing devices when a user is deleted."""

from __future__ import annotations

from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from magister_api.config import Settings
from magister_api.models.auth import AdUserCache
from magister_api.models.base import utcnow
from magister_api.models.device import Device
from magister_api.models.device_assignment import DeviceAssignment
from magister_api.services.devices import release_person_devices

pytestmark = pytest.mark.postgres

P1 = "00000000-0000-0000-0000-0000000d0001"
P2 = "00000000-0000-0000-0000-0000000d0002"


async def _seed_person(db: AsyncSession, guid: str, school_id: int, name: str) -> None:
    db.add(
        AdUserCache(
            ad_object_guid=guid,
            upn=f"{name}@schule.ch",
            sam_account_name=name,
            display_name=name,
            kind="student",
            enabled=True,
            school_id=school_id,
        )
    )
    await db.commit()


async def _assign(client: AsyncClient, device_id: int, body: dict[str, Any]) -> None:
    r = await client.post(f"/devices/{device_id}/assign", json=body)
    assert r.status_code == 200, r.text


@pytest.mark.asyncio
async def test_history_tracks_holders_and_loan(
    as_admin: AsyncClient, db_session: AsyncSession, school_a: int
) -> None:
    await _seed_person(db_session, P1, school_a, "anna")
    await _seed_person(db_session, P2, school_a, "beat")
    dev = (await as_admin.post("/devices", json={"name": "iPad-1"})).json()

    # P1 fixed → P2 as loaner → free.
    await _assign(as_admin, dev["id"], {"assignment_type": "person", "person_guid": P1})
    await _assign(
        as_admin, dev["id"], {"assignment_type": "person", "person_guid": P2, "is_loan": True}
    )
    await _assign(as_admin, dev["id"], {"assignment_type": "free"})

    history = (await as_admin.get(f"/devices/{dev['id']}/history")).json()
    # Newest first: P2 (loaner), then P1.
    assert [h["label"] for h in history] == ["beat", "anna"]
    assert history[0]["is_loan"] is True
    assert history[1]["is_loan"] is False
    # All periods are closed now (device is free).
    assert all(h["valid_to"] is not None for h in history)


@pytest.mark.asyncio
async def test_release_person_devices_frees_and_closes_history(
    engine: AsyncEngine, app_settings: Settings, school_a: int
) -> None:
    sm = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
    async with sm() as s:
        s.add(
            AdUserCache(
                ad_object_guid=P1,
                upn="carla@schule.ch",
                sam_account_name="carla",
                display_name="carla",
                kind="student",
                enabled=True,
                school_id=school_a,
            )
        )
        dev = Device(name="Laptop-1", assigned_person_guid=P1, school_id=school_a)
        s.add(dev)
        await s.flush()
        dev_id = dev.id
        s.add(
            DeviceAssignment(
                device_id=dev_id,
                assignment_type="person",
                assigned_person_guid=P1,
                label="carla",
                is_loan=False,
                valid_from=utcnow(),
                valid_to=None,
            )
        )
        await s.commit()

        freed = await release_person_devices(
            s,
            app_settings,
            P1,
            actor_upn="admin@example.ch",
            actor_object_guid=None,
            ip=None,
            request_id="req-del",
        )
        await s.commit()
        assert freed == 1

    async with sm() as s:
        row = await s.get(Device, dev_id)
        assert row is not None
        assert row.assigned_person_guid is None
        assert row.school_id is None
        assert row.is_loan is False
        hist = (
            await s.execute(select(DeviceAssignment).where(DeviceAssignment.device_id == dev_id))
        ).scalar_one()
        assert hist.valid_to is not None  # open period was closed on release
