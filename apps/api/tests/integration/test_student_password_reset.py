"""End-to-end ``POST /students/{guid}/password-reset`` — DoD coverage for issue #7."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from magister_api.ad.client import AdClient
from magister_api.audit.service import AuditService
from magister_api.config import Settings
from magister_api.models.audit import AuditEvent
from magister_api.models.auth import AdUserCache
from magister_api.routers.admin_sync import get_ad_client
from tests.integration._helpers import seed_user_with_session

if TYPE_CHECKING:
    from fastapi import FastAPI
    from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.postgres

STUDENT_GUID = "00000000-0000-0000-0000-000000aaaaaa"
KL_GUID = "00000000-0000-0000-0000-0000000000cc"
OTHER_KL_GUID = "00000000-0000-0000-0000-0000000000dd"
STRANGER_STUDENT_GUID = "00000000-0000-0000-0000-000000bbbbbb"


def _le(g: str) -> bytes:
    return uuid.UUID(g).bytes_le


@pytest_asyncio.fixture
async def mock_ad_with_students(app_settings: Settings):
    """AdClient backed by MOCK_SYNC, seeded with a student entry for find_user_dn."""
    settings = app_settings.model_copy(
        update={"ad_use_mock": True, "ad_users_search_base": "DC=schule,DC=local"}
    )
    client = AdClient(settings)
    conn = client.mock_connection()
    for guid, dn, enabled in [
        (
            STUDENT_GUID,
            "CN=Stud,OU=Students,DC=schule,DC=local",
            True,
        ),
        (
            STRANGER_STUDENT_GUID,
            "CN=Stranger,OU=Students,DC=schule,DC=local",
            True,
        ),
    ]:
        conn.strategy.add_entry(
            dn,
            {
                "objectClass": ["user"],
                "objectGUID": _le(guid),
                "userPrincipalName": f"{guid[:6]}@example.ch",
                "userAccountControl": 0x200 if enabled else (0x200 | 0x0002),
            },
        )
    yield client
    await client.aclose()


async def _seed_student(
    db_session: AsyncSession, school_id: int, guid: str = STUDENT_GUID, *, enabled: bool = True
) -> None:
    db_session.add(
        AdUserCache(
            ad_object_guid=guid,
            school_id=school_id,
            upn=f"{guid[:6]}@example.ch",
            kind="student",
            enabled=enabled,
        )
    )
    await db_session.flush()
    await db_session.commit()


async def _audit_actions(engine: AsyncEngine) -> list[str]:
    sm = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
    async with sm() as s:
        return list(
            (await s.execute(select(AuditEvent.action).order_by(AuditEvent.id))).scalars().all()
        )


async def _kl_client(
    *,
    app: FastAPI,
    app_settings: Settings,
    db_session: AsyncSession,
    school_id: int,
    cid: int,
    kl_guid: str,
    upn: str,
) -> AsyncClient:
    """Seed a teacher with an active KL role for ``cid`` and return an authed client."""
    sid, csrf = await seed_user_with_session(
        session=db_session,
        settings=app_settings,
        upn=upn,
        ad_object_guid=kl_guid,
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


# --- Helper to fully wire a class with a KL role + a student membership.


async def _wire_class_with_kl_and_student(
    *,
    as_schulleitung_a: AsyncClient,
    db_session: AsyncSession,
    school_id: int,
    kl_guid: str = KL_GUID,
    student_guid: str = STUDENT_GUID,
) -> int:
    r = await as_schulleitung_a.post(
        "/classes", json={"name": f"4a-{kl_guid[:4]}", "jahrgangsstufe": 4}
    )
    assert r.status_code == 201, r.text
    cid = r.json()["id"]
    now = datetime.now(UTC)
    r = await as_schulleitung_a.post(
        f"/classes/{cid}/teachers",
        json={
            "ad_object_guid": kl_guid,
            "role": "haupt",
            "valid_from": (now - timedelta(seconds=1)).isoformat(),
        },
    )
    assert r.status_code == 201, r.text
    await _seed_student(db_session, school_id, guid=student_guid)
    r = await as_schulleitung_a.post(
        f"/classes/{cid}/students",
        json={"ad_object_guid": student_guid},
    )
    assert r.status_code == 201, r.text
    return cid


class TestGenerateMode:
    @pytest.mark.asyncio
    async def test_kl_gets_temp_password_once_and_audit_has_no_plaintext(
        self,
        app: FastAPI,
        as_schulleitung_a: AsyncClient,
        app_settings: Settings,
        db_session: AsyncSession,
        school_a: int,
        engine: AsyncEngine,
        mock_ad_with_students: AdClient,
    ) -> None:
        await _wire_class_with_kl_and_student(
            as_schulleitung_a=as_schulleitung_a,
            db_session=db_session,
            school_id=school_a,
        )
        app.dependency_overrides[get_ad_client] = lambda: mock_ad_with_students
        try:
            kl = await _kl_client(
                app=app,
                app_settings=app_settings,
                db_session=db_session,
                school_id=school_a,
                cid=0,
                kl_guid=KL_GUID,
                upn="kl-anna@example.ch",
            )
            async with kl:
                r = await kl.post(
                    f"/students/{STUDENT_GUID}/password-reset",
                    json={"mode": "generate"},
                )
                assert r.status_code == 200, r.text
                body = r.json()
                assert body["mode"] == "generate"
                assert body["force_change"] is True
                temp_pw = body["temp_password"]
                assert temp_pw and len(temp_pw) >= 12
        finally:
            app.dependency_overrides.pop(get_ad_client, None)

        # Audit emitted, payload contains NO plaintext password.
        sm = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
        async with sm() as s:
            row = (
                (
                    await s.execute(
                        select(AuditEvent)
                        .where(AuditEvent.action == "student_password_reset")
                        .order_by(AuditEvent.id.desc())
                    )
                )
                .scalars()
                .first()
            )
            assert row is not None
            event = await AuditService(s, app_settings).read(row.id)
        assert event is not None
        assert event.payload["mode"] == "generate"
        assert event.payload["force_change"] is True
        assert "temp_password" not in event.payload
        assert "manual_password" not in event.payload
        # Belt-and-braces: the actual generated PW must not appear anywhere.
        assert temp_pw not in repr(event.payload)


class TestManualMode:
    @pytest.mark.asyncio
    async def test_compliant_manual_password_accepted(
        self,
        app: FastAPI,
        as_schulleitung_a: AsyncClient,
        app_settings: Settings,
        db_session: AsyncSession,
        school_a: int,
        mock_ad_with_students: AdClient,
    ) -> None:
        await _wire_class_with_kl_and_student(
            as_schulleitung_a=as_schulleitung_a,
            db_session=db_session,
            school_id=school_a,
        )
        app.dependency_overrides[get_ad_client] = lambda: mock_ad_with_students
        try:
            kl = await _kl_client(
                app=app,
                app_settings=app_settings,
                db_session=db_session,
                school_id=school_a,
                cid=0,
                kl_guid=KL_GUID,
                upn="kl-anna@example.ch",
            )
            async with kl:
                r = await kl.post(
                    f"/students/{STUDENT_GUID}/password-reset",
                    json={
                        "mode": "manual",
                        "manual_password": "Apfel-Stuhl-77!",
                        "force_change": False,
                    },
                )
                assert r.status_code == 200, r.text
                body = r.json()
                assert body["mode"] == "manual"
                assert body["force_change"] is False
                assert body.get("temp_password") is None
        finally:
            app.dependency_overrides.pop(get_ad_client, None)

    @pytest.mark.asyncio
    async def test_weak_manual_password_rejected(
        self,
        app: FastAPI,
        as_schulleitung_a: AsyncClient,
        app_settings: Settings,
        db_session: AsyncSession,
        school_a: int,
        mock_ad_with_students: AdClient,
    ) -> None:
        await _wire_class_with_kl_and_student(
            as_schulleitung_a=as_schulleitung_a,
            db_session=db_session,
            school_id=school_a,
        )
        app.dependency_overrides[get_ad_client] = lambda: mock_ad_with_students
        try:
            kl = await _kl_client(
                app=app,
                app_settings=app_settings,
                db_session=db_session,
                school_id=school_a,
                cid=0,
                kl_guid=KL_GUID,
                upn="kl-anna@example.ch",
            )
            async with kl:
                r = await kl.post(
                    f"/students/{STUDENT_GUID}/password-reset",
                    json={"mode": "manual", "manual_password": "alllower12345"},
                )
                assert r.status_code == 422
                assert "policy" in r.json()["detail"]
        finally:
            app.dependency_overrides.pop(get_ad_client, None)


class TestRbac:
    @pytest.mark.asyncio
    async def test_kl_of_other_class_blocked(
        self,
        app: FastAPI,
        as_schulleitung_a: AsyncClient,
        app_settings: Settings,
        db_session: AsyncSession,
        school_a: int,
        mock_ad_with_students: AdClient,
    ) -> None:
        # Student is in class A with KL_GUID as KL.
        await _wire_class_with_kl_and_student(
            as_schulleitung_a=as_schulleitung_a,
            db_session=db_session,
            school_id=school_a,
        )
        # Create another class with a different KL.
        r = await as_schulleitung_a.post("/classes", json={"name": "5a", "jahrgangsstufe": 5})
        cid_other = r.json()["id"]
        now = datetime.now(UTC)
        r = await as_schulleitung_a.post(
            f"/classes/{cid_other}/teachers",
            json={
                "ad_object_guid": OTHER_KL_GUID,
                "role": "haupt",
                "valid_from": (now - timedelta(seconds=1)).isoformat(),
            },
        )
        assert r.status_code == 201

        app.dependency_overrides[get_ad_client] = lambda: mock_ad_with_students
        try:
            other_kl = await _kl_client(
                app=app,
                app_settings=app_settings,
                db_session=db_session,
                school_id=school_a,
                cid=cid_other,
                kl_guid=OTHER_KL_GUID,
                upn="kl-other@example.ch",
            )
            async with other_kl:
                r = await other_kl.post(
                    f"/students/{STUDENT_GUID}/password-reset",
                    json={"mode": "generate"},
                )
                # 404 student_not_found — no leak that the student exists.
                assert r.status_code == 404
                assert r.json()["detail"] == "student_not_found"
        finally:
            app.dependency_overrides.pop(get_ad_client, None)

    @pytest.mark.asyncio
    async def test_disabled_student_blocked(
        self,
        app: FastAPI,
        as_schulleitung_a: AsyncClient,
        app_settings: Settings,
        db_session: AsyncSession,
        school_a: int,
        mock_ad_with_students: AdClient,
    ) -> None:
        # Wire class + KL + membership.
        await _wire_class_with_kl_and_student(
            as_schulleitung_a=as_schulleitung_a,
            db_session=db_session,
            school_id=school_a,
        )
        # Mark the student as disabled in the cache.
        student = await db_session.get(AdUserCache, STUDENT_GUID)
        assert student is not None
        student.enabled = False
        await db_session.commit()

        app.dependency_overrides[get_ad_client] = lambda: mock_ad_with_students
        try:
            kl = await _kl_client(
                app=app,
                app_settings=app_settings,
                db_session=db_session,
                school_id=school_a,
                cid=0,
                kl_guid=KL_GUID,
                upn="kl-anna@example.ch",
            )
            async with kl:
                r = await kl.post(
                    f"/students/{STUDENT_GUID}/password-reset",
                    json={"mode": "generate"},
                )
                assert r.status_code == 409
                assert r.json()["detail"] == "student_disabled"
        finally:
            app.dependency_overrides.pop(get_ad_client, None)


class TestAdOutage:
    @pytest.mark.asyncio
    async def test_503_on_ad_unavailable(
        self,
        app: FastAPI,
        as_schulleitung_a: AsyncClient,
        app_settings: Settings,
        db_session: AsyncSession,
        school_a: int,
    ) -> None:
        await _wire_class_with_kl_and_student(
            as_schulleitung_a=as_schulleitung_a,
            db_session=db_session,
            school_id=school_a,
        )
        # Live mode with no DCs -> AdUnavailableError on first ldap call.
        broken = AdClient(app_settings.model_copy(update={"ad_use_mock": False, "ad_dcs": []}))
        app.dependency_overrides[get_ad_client] = lambda: broken
        try:
            kl = await _kl_client(
                app=app,
                app_settings=app_settings,
                db_session=db_session,
                school_id=school_a,
                cid=0,
                kl_guid=KL_GUID,
                upn="kl-anna@example.ch",
            )
            async with kl:
                r = await kl.post(
                    f"/students/{STUDENT_GUID}/password-reset",
                    json={"mode": "generate"},
                )
                assert r.status_code == 503
                assert r.json()["detail"] == "ad_unavailable"
        finally:
            app.dependency_overrides.pop(get_ad_client, None)


class TestSchemaGuards:
    @pytest.mark.asyncio
    async def test_manual_without_password_422(
        self,
        app: FastAPI,
        as_schulleitung_a: AsyncClient,
        app_settings: Settings,
        db_session: AsyncSession,
        school_a: int,
        mock_ad_with_students: AdClient,
    ) -> None:
        await _wire_class_with_kl_and_student(
            as_schulleitung_a=as_schulleitung_a,
            db_session=db_session,
            school_id=school_a,
        )
        app.dependency_overrides[get_ad_client] = lambda: mock_ad_with_students
        try:
            kl = await _kl_client(
                app=app,
                app_settings=app_settings,
                db_session=db_session,
                school_id=school_a,
                cid=0,
                kl_guid=KL_GUID,
                upn="kl-anna@example.ch",
            )
            async with kl:
                r = await kl.post(
                    f"/students/{STUDENT_GUID}/password-reset",
                    json={"mode": "manual"},
                )
                assert r.status_code == 422
        finally:
            app.dependency_overrides.pop(get_ad_client, None)

    @pytest.mark.asyncio
    async def test_generate_with_manual_password_422(
        self,
        app: FastAPI,
        as_schulleitung_a: AsyncClient,
        app_settings: Settings,
        db_session: AsyncSession,
        school_a: int,
        mock_ad_with_students: AdClient,
    ) -> None:
        await _wire_class_with_kl_and_student(
            as_schulleitung_a=as_schulleitung_a,
            db_session=db_session,
            school_id=school_a,
        )
        app.dependency_overrides[get_ad_client] = lambda: mock_ad_with_students
        try:
            kl = await _kl_client(
                app=app,
                app_settings=app_settings,
                db_session=db_session,
                school_id=school_a,
                cid=0,
                kl_guid=KL_GUID,
                upn="kl-anna@example.ch",
            )
            async with kl:
                r = await kl.post(
                    f"/students/{STUDENT_GUID}/password-reset",
                    json={"mode": "generate", "manual_password": "Whatever-12!"},
                )
                assert r.status_code == 422
        finally:
            app.dependency_overrides.pop(get_ad_client, None)
