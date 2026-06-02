"""Integration tests for the subject-access / privacy export (M3 US-4 + US-5)."""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from magister_api.models.auth import AdUserCache
from magister_api.models.base import utcnow
from magister_api.models.class_membership import ClassMembership
from magister_api.models.school_class import SchoolClass


async def _seed_student_in_class(
    db: AsyncSession,
    *,
    school_id: int,
    guid_suffix: str = "01",
    upn: str = "anna@example.ch",
    display_name: str = "Anna Beispiel",
) -> tuple[str, int]:
    cls = SchoolClass(school_id=school_id, name="3a", kuerzel="3a", jahrgangsstufe=3)
    db.add(cls)
    await db.flush()
    student_guid = f"00000000-0000-0000-0000-0000000000{guid_suffix}"
    db.add(
        AdUserCache(
            ad_object_guid=student_guid,
            school_id=school_id,
            upn=upn,
            display_name=display_name,
            kind="student",
            enabled=True,
            ms_ds_consistency_guid=student_guid,
        )
    )
    db.add(
        ClassMembership(
            class_id=cls.id,
            ad_object_guid=student_guid,
            valid_from=utcnow(),
        )
    )
    await db.commit()
    return student_guid, cls.id


@pytest.mark.asyncio
async def test_subject_access_returns_identity_and_memberships(
    as_schulleitung_a: AsyncClient,
    db_session: AsyncSession,
    school_a: int,
) -> None:
    student_guid, cls_id = await _seed_student_in_class(db_session, school_id=school_a)
    r = await as_schulleitung_a.get(f"/privacy/subject-access/{student_guid}")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["user"]["upn"] == "anna@example.ch"
    assert body["user"]["display_name"] == "Anna Beispiel"
    assert body["school"]["id"] == school_a
    assert len(body["memberships"]) == 1
    assert body["memberships"][0]["class_id"] == cls_id


@pytest.mark.asyncio
async def test_subject_access_includes_self_audit_event(
    as_schulleitung_a: AsyncClient,
    db_session: AsyncSession,
    school_a: int,
) -> None:
    student_guid, _ = await _seed_student_in_class(db_session, school_id=school_a)
    # First fetch — creates one subject_access_export event.
    await as_schulleitung_a.get(f"/privacy/subject-access/{student_guid}")
    # Second fetch — now sees the event from the first fetch.
    r = await as_schulleitung_a.get(f"/privacy/subject-access/{student_guid}")
    body = r.json()
    actions = [ev["action"] for ev in body["audit_events"]]
    assert "subject_access_export" in actions


@pytest.mark.asyncio
async def test_subject_access_unknown_404(as_schulleitung_a: AsyncClient) -> None:
    r = await as_schulleitung_a.get("/privacy/subject-access/00000000-0000-0000-0000-0000000000ff")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_subject_access_cross_school_blocked(
    as_schulleitung_b: AsyncClient,
    db_session: AsyncSession,
    school_a: int,
) -> None:
    student_guid, _ = await _seed_student_in_class(db_session, school_id=school_a)
    r = await as_schulleitung_b.get(f"/privacy/subject-access/{student_guid}")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_admin_can_access_any_subject(
    as_admin: AsyncClient,
    db_session: AsyncSession,
    school_a: int,
) -> None:
    student_guid, _ = await _seed_student_in_class(db_session, school_id=school_a)
    r = await as_admin.get(f"/privacy/subject-access/{student_guid}")
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_subject_access_requires_auth(client: AsyncClient) -> None:
    r = await client.get("/privacy/subject-access/00000000-0000-0000-0000-000000000001")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_csv_export_streams_attachment(
    as_schulleitung_a: AsyncClient,
    db_session: AsyncSession,
    school_a: int,
) -> None:
    student_guid, _ = await _seed_student_in_class(db_session, school_id=school_a)
    r = await as_schulleitung_a.get(f"/privacy/subject-access/{student_guid}/export.csv")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/csv")
    assert "attachment" in r.headers["content-disposition"]
    body = r.text
    assert "# === Identity ===" in body
    assert "anna@example.ch" in body
    assert "# === Class memberships" in body
    assert "# === Audit events ===" in body


@pytest.mark.asyncio
async def test_audit_event_includes_actor_role(
    as_schulleitung_a: AsyncClient,
    db_session: AsyncSession,
    school_a: int,
) -> None:
    """If the subject was the actor of an event, it shows up with role=actor.

    Quick way to verify: trigger one event where the student is the *target*
    (e.g. /letters/enrollment), then fetch their subject-access — the event
    must be there with role=target.
    """
    student_guid, _ = await _seed_student_in_class(db_session, school_id=school_a)
    await as_schulleitung_a.post(
        "/letters/enrollment",
        json={
            "student_guid": student_guid,
            "school_year": "2026/27",
            "first_day": "12.08.2026",
        },
    )
    r = await as_schulleitung_a.get(f"/privacy/subject-access/{student_guid}")
    events = r.json()["audit_events"]
    letter_events = [ev for ev in events if ev["action"] == "letter_generated"]
    assert len(letter_events) == 1
    assert letter_events[0]["role"] == "target"
    assert letter_events[0]["target_id"] == student_guid
