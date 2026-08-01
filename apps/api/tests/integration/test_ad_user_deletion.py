"""AD deletion: full-sync 'missing' marking + hard-delete endpoint."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select

from magister_api.ad.client import AdClient
from magister_api.config import Settings
from magister_api.models.audit import AuditEvent
from magister_api.models.auth import AdUserCache
from magister_api.models.base import utcnow
from magister_api.models.class_membership import ClassMembership
from magister_api.models.school_class import SchoolClass
from magister_api.routers.admin_sync import get_ad_client
from magister_api.services.ad_sync import AdSyncService

if TYPE_CHECKING:
    from fastapi import FastAPI
    from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.postgres

PRESENT = "00000000-0000-0000-0000-000000000101"
GONE = "00000000-0000-0000-0000-000000000102"
STUD = "00000000-0000-0000-0000-000000000103"
ADMIN = "00000000-0000-0000-0000-000000000104"


def _le(g: str) -> bytes:
    return uuid.UUID(g).bytes_le


def _mock_ad(app_settings: Settings, entries: list[tuple[str, str]]) -> AdClient:
    settings = app_settings.model_copy(
        update={"ad_use_mock": True, "ad_users_search_base": "DC=schule,DC=local"}
    )
    client = AdClient(settings)
    conn = client.mock_connection()
    # Seed the base container so a user search over an empty tree returns [] with
    # success (the mock errors when the search base itself has no entries).
    conn.strategy.add_entry("DC=schule,DC=local", {"objectClass": ["domain"]})
    for guid, dn in entries:
        conn.strategy.add_entry(
            dn,
            {
                "objectClass": ["user"],
                "objectGUID": _le(guid),
                "userPrincipalName": f"{guid}@schule.example.ch",
                "givenName": "X",
                "sn": "Y",
                "userAccountControl": 0x200,
            },
        )
    return client


def _sync_settings(app_settings: Settings, **extra: object) -> Settings:
    return app_settings.model_copy(
        update={"ad_use_mock": True, "ad_users_search_base": "DC=schule,DC=local", **extra}
    )


async def _add_student(db_session: AsyncSession, guid: str, **kw: object) -> None:
    db_session.add(
        AdUserCache(
            ad_object_guid=guid,
            upn=f"{guid}@schule.example.ch",
            kind=kw.pop("kind", "student"),
            enabled=True,
            **kw,
        )
    )


# ---------------------------------------------------------------------------
# Full-sync reconcile (marking)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_full_sync_flags_absent_and_clears_present(
    db_session: AsyncSession, app_settings: Settings
) -> None:
    await _add_student(db_session, PRESENT)
    await _add_student(db_session, GONE)
    await db_session.commit()

    ad = _mock_ad(app_settings, [(PRESENT, "CN=P,OU=Students,DC=schule,DC=local")])
    svc = AdSyncService(db_session, _sync_settings(app_settings), ad)
    await svc.sync_all(
        actor_upn="admin@example.ch", actor_object_guid=None, ip=None, request_id="r1", mode="full"
    )
    await db_session.commit()

    gone = await db_session.get(AdUserCache, GONE)
    present = await db_session.get(AdUserCache, PRESENT)
    assert gone is not None and gone.ad_missing_since is not None
    assert present is not None and present.ad_missing_since is None
    await ad.aclose()


@pytest.mark.asyncio
async def test_reappearing_user_clears_marker(
    db_session: AsyncSession, app_settings: Settings
) -> None:
    await _add_student(db_session, GONE, ad_missing_since=utcnow())
    await db_session.commit()

    ad = _mock_ad(app_settings, [(GONE, "CN=G,OU=Students,DC=schule,DC=local")])
    svc = AdSyncService(db_session, _sync_settings(app_settings), ad)
    await svc.sync_all(
        actor_upn="a@example.ch", actor_object_guid=None, ip=None, request_id="r2", mode="full"
    )
    await db_session.commit()

    row = await db_session.get(AdUserCache, GONE)
    assert row is not None and row.ad_missing_since is None
    await ad.aclose()


@pytest.mark.asyncio
async def test_threshold_guard_skips_mass_marking(
    db_session: AsyncSession, app_settings: Settings
) -> None:
    await _add_student(db_session, PRESENT)
    for i in range(4):
        await _add_student(db_session, f"00000000-0000-0000-0000-00000000020{i}")
    await db_session.commit()

    ad = _mock_ad(app_settings, [(PRESENT, "CN=P,OU=Students,DC=schule,DC=local")])
    # floor=0, ratio=0.2 → limit=1; 4 candidates > 1 → skip.
    svc = AdSyncService(db_session, _sync_settings(app_settings, ad_sync_missing_floor=0), ad)
    await svc.sync_all(
        actor_upn="a@example.ch", actor_object_guid=None, ip=None, request_id="r4", mode="full"
    )
    await db_session.commit()

    flagged = (
        await db_session.execute(
            select(func.count())
            .select_from(AdUserCache)
            .where(AdUserCache.ad_missing_since.is_not(None))
        )
    ).scalar_one()
    assert flagged == 0
    events = (
        (
            await db_session.execute(
                select(AuditEvent).where(AuditEvent.action == "ad_sync_missing_skipped_threshold")
            )
        )
        .scalars()
        .all()
    )
    assert len(events) == 1
    await ad.aclose()


# ---------------------------------------------------------------------------
# Hard-delete endpoint
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_flagged_student_cascades(
    as_admin: AsyncClient,
    app: FastAPI,
    db_session: AsyncSession,
    school_a: int,
    app_settings: Settings,
) -> None:
    cls = SchoolClass(school_id=school_a, name="9z", kuerzel="9z", jahrgangsstufe=9)
    db_session.add(cls)
    await db_session.flush()
    await _add_student(db_session, STUD, school_id=school_a, ad_missing_since=utcnow())
    db_session.add(ClassMembership(class_id=cls.id, ad_object_guid=STUD, valid_from=utcnow()))
    await db_session.commit()

    ad = _mock_ad(app_settings, [])
    app.dependency_overrides[get_ad_client] = lambda: ad
    try:
        r = await as_admin.delete(f"/users/{STUD}")
    finally:
        app.dependency_overrides.pop(get_ad_client, None)
    assert r.status_code == 200, r.text
    assert r.json()["class_memberships"] == 1

    assert await db_session.get(AdUserCache, STUD) is None
    remaining = (
        await db_session.execute(
            select(func.count())
            .select_from(ClassMembership)
            .where(ClassMembership.ad_object_guid == STUD)
        )
    ).scalar_one()
    assert remaining == 0
    events = (
        (await db_session.execute(select(AuditEvent).where(AuditEvent.action == "ad_user_deleted")))
        .scalars()
        .all()
    )
    assert len(events) == 1
    await ad.aclose()


@pytest.mark.asyncio
async def test_delete_refuses_user_still_in_ad(
    as_admin: AsyncClient,
    app: FastAPI,
    db_session: AsyncSession,
    school_a: int,
    app_settings: Settings,
) -> None:
    await _add_student(db_session, STUD, school_id=school_a)  # not flagged
    await db_session.commit()
    ad = _mock_ad(app_settings, [(STUD, "CN=S,OU=Students,DC=schule,DC=local")])  # still in AD
    app.dependency_overrides[get_ad_client] = lambda: ad
    try:
        r = await as_admin.delete(f"/users/{STUD}")
    finally:
        app.dependency_overrides.pop(get_ad_client, None)
    assert r.status_code == 409
    assert r.json()["detail"] == "user_still_in_ad"
    assert await db_session.get(AdUserCache, STUD) is not None
    await ad.aclose()


@pytest.mark.asyncio
async def test_delete_refuses_admin_kind(
    as_admin: AsyncClient,
    app: FastAPI,
    db_session: AsyncSession,
    school_a: int,
    app_settings: Settings,
) -> None:
    await _add_student(
        db_session, ADMIN, school_id=school_a, kind="admin", ad_missing_since=utcnow()
    )
    await db_session.commit()
    ad = _mock_ad(app_settings, [])
    app.dependency_overrides[get_ad_client] = lambda: ad
    try:
        r = await as_admin.delete(f"/users/{ADMIN}")
    finally:
        app.dependency_overrides.pop(get_ad_client, None)
    assert r.status_code == 409
    assert r.json()["detail"] == "cannot_delete_non_student_teacher"
    await ad.aclose()


@pytest.mark.asyncio
async def test_delete_requires_user_writer(as_schulleitung_a: AsyncClient) -> None:
    r = await as_schulleitung_a.delete(f"/users/{STUD}")
    assert r.status_code in (403, 404)


@pytest.mark.asyncio
async def test_list_missing_filter(
    as_admin: AsyncClient, db_session: AsyncSession, school_a: int
) -> None:
    await _add_student(db_session, GONE, school_id=school_a, ad_missing_since=utcnow())
    await _add_student(db_session, PRESENT, school_id=school_a)
    await db_session.commit()
    r = await as_admin.get("/users?missing=true")
    assert r.status_code == 200, r.text
    guids = {i["ad_object_guid"] for i in r.json()["items"]}
    assert GONE in guids
    assert PRESENT not in guids
