"""POST /classes/{id}/promote — move all or a selected subset of students."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from magister_api.models.class_membership import ClassMembership
from magister_api.models.school_class import CLASS_STATUS_ACTIVE, SchoolClass

pytestmark = pytest.mark.postgres

S1 = "00000000-0000-0000-0000-0000000000a1"
S2 = "00000000-0000-0000-0000-0000000000a2"


async def _class(session: AsyncSession, *, school_id: int, name: str) -> int:
    cls = SchoolClass(
        school_id=school_id, name=name, kuerzel=None, jahrgangsstufe=3, status=CLASS_STATUS_ACTIVE
    )
    session.add(cls)
    await session.flush()
    return cls.id


async def _member(session: AsyncSession, *, class_id: int, guid: str) -> None:
    session.add(
        ClassMembership(
            class_id=class_id,
            ad_object_guid=guid,
            valid_from=datetime.now(UTC) - timedelta(days=1),
            valid_to=None,
        )
    )


async def _active_guids(client: AsyncClient, class_id: int) -> set[str]:
    r = await client.get(f"/classes/{class_id}/students")
    assert r.status_code == 200, r.text
    return {s["ad_object_guid"] for s in r.json() if s["valid_to"] is None}


@pytest.mark.asyncio
async def test_promote_all_students(
    as_schulleitung_a: AsyncClient, db_session: AsyncSession, school_a: int
) -> None:
    src = await _class(db_session, school_id=school_a, name="3a")
    dst = await _class(db_session, school_id=school_a, name="4a")
    await _member(db_session, class_id=src, guid=S1)
    await _member(db_session, class_id=src, guid=S2)
    await db_session.commit()

    r = await as_schulleitung_a.post(f"/classes/{src}/promote", json={"target_class_id": dst})
    assert r.status_code == 200, r.text
    assert r.json()["students_moved"] == 2
    assert await _active_guids(as_schulleitung_a, dst) == {S1, S2}
    assert await _active_guids(as_schulleitung_a, src) == set()


@pytest.mark.asyncio
async def test_promote_selected_subset(
    as_schulleitung_a: AsyncClient, db_session: AsyncSession, school_a: int
) -> None:
    src = await _class(db_session, school_id=school_a, name="3b")
    dst = await _class(db_session, school_id=school_a, name="4b")
    await _member(db_session, class_id=src, guid=S1)
    await _member(db_session, class_id=src, guid=S2)
    await db_session.commit()

    # Only move S1.
    r = await as_schulleitung_a.post(
        f"/classes/{src}/promote",
        json={"target_class_id": dst, "student_guids": [S1]},
    )
    assert r.status_code == 200, r.text
    assert r.json()["students_moved"] == 1
    assert await _active_guids(as_schulleitung_a, dst) == {S1}
    # S2 stays in the source class.
    assert await _active_guids(as_schulleitung_a, src) == {S2}
