"""Class-detail multi-select features: advance/move students + class devices."""

from __future__ import annotations

from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from magister_api.models.auth import AdUserCache

pytestmark = pytest.mark.postgres

S1 = "00000000-0000-0000-0000-00000000a001"
S2 = "00000000-0000-0000-0000-00000000a002"


async def _seed_student(db: AsyncSession, guid: str, school_id: int, grade: int) -> None:
    db.add(
        AdUserCache(
            ad_object_guid=guid,
            upn=f"s{guid[-4:]}@schule.ch",
            sam_account_name=f"s{guid[-4:]}",
            kind="student",
            enabled=True,
            school_id=school_id,
            jahrgangsstufe=grade,
        )
    )
    await db.commit()


async def _class(client: AsyncClient, school_id: int, name: str, grade: int) -> int:
    r = await client.post(
        "/classes", json={"name": name, "jahrgangsstufe": grade, "school_id": school_id}
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def _grade(db: AsyncSession, guid: str) -> int | None:
    db.expire_all()
    return (
        await db.execute(
            select(AdUserCache.jahrgangsstufe).where(AdUserCache.ad_object_guid == guid)
        )
    ).scalar_one()


@pytest.mark.asyncio
async def test_roster_includes_jahrgangsstufe(
    as_admin: AsyncClient, db_session: AsyncSession, school_a: int
) -> None:
    await _seed_student(db_session, S1, school_a, 3)
    cid = await _class(as_admin, school_a, "3a", 3)
    r = await as_admin.post(f"/classes/{cid}/students", json={"ad_object_guid": S1})
    assert r.status_code == 201, r.text

    roster = (await as_admin.get(f"/classes/{cid}/students")).json()
    assert roster[0]["jahrgangsstufe"] == 3


@pytest.mark.asyncio
async def test_advance_keeps_class_bumps_grade(
    as_admin: AsyncClient, db_session: AsyncSession, school_a: int
) -> None:
    await _seed_student(db_session, S1, school_a, 3)
    cid = await _class(as_admin, school_a, "3a", 3)
    await as_admin.post(f"/classes/{cid}/students", json={"ad_object_guid": S1})

    # No target → class stays, only the school year rises.
    r = await as_admin.post(
        f"/classes/{cid}/advance", json={"student_guids": [S1], "grade_delta": 1}
    )
    assert r.status_code == 200, r.text
    assert r.json()["students_moved"] == 1

    assert await _grade(db_session, S1) == 4
    # Still a member of the same class.
    roster = (await as_admin.get(f"/classes/{cid}/students")).json()
    assert [m["ad_object_guid"] for m in roster] == [S1]


@pytest.mark.asyncio
async def test_advance_moves_to_other_class(
    as_admin: AsyncClient, db_session: AsyncSession, school_a: int
) -> None:
    await _seed_student(db_session, S1, school_a, 3)
    src = await _class(as_admin, school_a, "3a", 3)
    tgt = await _class(as_admin, school_a, "4a", 4)
    # valid_from in the past so ending the old membership ("now - 1s") stays
    # at/after valid_from (a student is never moved in the same second added).
    await as_admin.post(
        f"/classes/{src}/students",
        json={"ad_object_guid": S1, "valid_from": "2026-01-06T00:00:00+00:00"},
    )

    r = await as_admin.post(
        f"/classes/{src}/advance",
        json={"student_guids": [S1], "target_class_id": tgt, "grade_delta": 1},
    )
    assert r.status_code == 200, r.text
    assert r.json()["students_moved"] == 1

    assert await _grade(db_session, S1) == 4
    assert (await as_admin.get(f"/classes/{src}/students")).json() == []
    moved = (await as_admin.get(f"/classes/{tgt}/students")).json()
    assert [m["ad_object_guid"] for m in moved] == [S1]


async def _assign(client: AsyncClient, device_id: int, body: dict[str, Any]) -> None:
    r = await client.post(f"/devices/{device_id}/assign", json=body)
    assert r.status_code == 200, r.text


@pytest.mark.asyncio
async def test_class_devices_lists_student_and_class_devices(
    as_admin: AsyncClient, db_session: AsyncSession, school_a: int
) -> None:
    await _seed_student(db_session, S1, school_a, 3)
    cid = await _class(as_admin, school_a, "3a", 3)
    await as_admin.post(f"/classes/{cid}/students", json={"ad_object_guid": S1})

    d_person = (await as_admin.post("/devices", json={"name": "iPad-Schueler"})).json()
    d_class = (await as_admin.post("/devices", json={"name": "Beamer-Klasse"})).json()
    await _assign(as_admin, d_person["id"], {"assignment_type": "person", "person_guid": S1})
    await _assign(as_admin, d_class["id"], {"assignment_type": "class", "class_id": cid})

    devices = (await as_admin.get(f"/classes/{cid}/devices")).json()
    by_name = {d["name"]: d for d in devices}
    assert by_name["iPad-Schueler"]["assignee_kind"] == "student"
    assert by_name["iPad-Schueler"]["assignee_label"]  # a resolved name, not empty
    assert by_name["Beamer-Klasse"]["assignee_kind"] == "class"
    assert by_name["Beamer-Klasse"]["assignee_label"] == "3a"
