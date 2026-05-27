"""End-to-end ``POST /teachers/{guid}/password-reset`` — SMI-only path."""

from __future__ import annotations

import uuid
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

if TYPE_CHECKING:
    from fastapi import FastAPI
    from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.postgres

TEACHER_GUID = "00000000-0000-0000-0000-0000000000a3"
OTHER_SCHOOL_TEACHER_GUID = "00000000-0000-0000-0000-0000000000b3"


def _le(g: str) -> bytes:
    return uuid.UUID(g).bytes_le


@pytest_asyncio.fixture
async def mock_ad_with_teachers(app_settings: Settings):
    settings = app_settings.model_copy(
        update={"ad_use_mock": True, "ad_users_search_base": "DC=schule,DC=local"}
    )
    client = AdClient(settings)
    conn = client.mock_connection()
    for guid, dn, enabled in [
        (TEACHER_GUID, "CN=T1,OU=Teachers,DC=schule,DC=local", True),
        (OTHER_SCHOOL_TEACHER_GUID, "CN=T2,OU=Teachers,DC=schule,DC=local", True),
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


async def _seed_teacher(
    db_session: AsyncSession,
    school_id: int,
    guid: str = TEACHER_GUID,
    *,
    enabled: bool = True,
) -> None:
    db_session.add(
        AdUserCache(
            ad_object_guid=guid,
            school_id=school_id,
            upn=f"{guid[:6]}@example.ch",
            kind="teacher",
            enabled=enabled,
        )
    )
    await db_session.flush()
    await db_session.commit()


class TestHappyPath:
    @pytest.mark.asyncio
    async def test_smi_can_reset_teacher_in_assigned_school(
        self,
        app: FastAPI,
        as_smi_a: AsyncClient,
        app_settings: Settings,
        db_session: AsyncSession,
        school_a: int,
        engine: AsyncEngine,
        mock_ad_with_teachers: AdClient,
    ) -> None:
        await _seed_teacher(db_session, school_a)
        app.dependency_overrides[get_ad_client] = lambda: mock_ad_with_teachers
        try:
            r = await as_smi_a.post(
                f"/teachers/{TEACHER_GUID}/password-reset",
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

        # Audit emits ``teacher_password_reset`` and never the plaintext.
        sm = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
        async with sm() as s:
            row = (
                (
                    await s.execute(
                        select(AuditEvent)
                        .where(AuditEvent.action == "teacher_password_reset")
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
        assert "temp_password" not in event.payload
        assert temp_pw not in repr(event.payload)

    @pytest.mark.asyncio
    async def test_admin_can_reset_teacher_cross_school(
        self,
        app: FastAPI,
        as_admin: AsyncClient,
        db_session: AsyncSession,
        school_a: int,
        mock_ad_with_teachers: AdClient,
    ) -> None:
        await _seed_teacher(db_session, school_a)
        app.dependency_overrides[get_ad_client] = lambda: mock_ad_with_teachers
        try:
            r = await as_admin.post(
                f"/teachers/{TEACHER_GUID}/password-reset",
                json={"mode": "generate"},
            )
            assert r.status_code == 200, r.text
        finally:
            app.dependency_overrides.pop(get_ad_client, None)


class TestRbac:
    @pytest.mark.asyncio
    async def test_schulleitung_blocked(
        self,
        app: FastAPI,
        as_schulleitung_a: AsyncClient,
        db_session: AsyncSession,
        school_a: int,
        mock_ad_with_teachers: AdClient,
    ) -> None:
        """Schulleitung must NOT reset teacher passwords — that's SMI territory."""
        await _seed_teacher(db_session, school_a)
        app.dependency_overrides[get_ad_client] = lambda: mock_ad_with_teachers
        try:
            r = await as_schulleitung_a.post(
                f"/teachers/{TEACHER_GUID}/password-reset",
                json={"mode": "generate"},
            )
            # 404 to avoid leaking that the teacher exists.
            assert r.status_code == 404
            assert r.json()["detail"] == "teacher_not_found"
        finally:
            app.dependency_overrides.pop(get_ad_client, None)

    @pytest.mark.asyncio
    async def test_smi_blocked_for_other_school_teacher(
        self,
        app: FastAPI,
        as_smi_a: AsyncClient,
        db_session: AsyncSession,
        school_b: int,
        mock_ad_with_teachers: AdClient,
    ) -> None:
        await _seed_teacher(db_session, school_b, guid=OTHER_SCHOOL_TEACHER_GUID)
        app.dependency_overrides[get_ad_client] = lambda: mock_ad_with_teachers
        try:
            r = await as_smi_a.post(
                f"/teachers/{OTHER_SCHOOL_TEACHER_GUID}/password-reset",
                json={"mode": "generate"},
            )
            assert r.status_code == 404
        finally:
            app.dependency_overrides.pop(get_ad_client, None)

    @pytest.mark.asyncio
    async def test_unauthenticated_blocked(
        self,
        app: FastAPI,
        client: AsyncClient,
    ) -> None:
        """CSRF middleware rejects the un-cookied POST before the route runs."""
        r = await client.post(
            f"/teachers/{TEACHER_GUID}/password-reset",
            json={"mode": "generate"},
        )
        assert r.status_code == 403

    @pytest.mark.asyncio
    async def test_kind_must_be_teacher(
        self,
        app: FastAPI,
        as_smi_a: AsyncClient,
        app_settings: Settings,
        db_session: AsyncSession,
        school_a: int,
        mock_ad_with_teachers: AdClient,
    ) -> None:
        """A non-teacher row at /teachers/... returns 400 not_a_teacher."""
        # Seed a *student* with the teacher fixture's guid → endpoint rejects.
        db_session.add(
            AdUserCache(
                ad_object_guid=TEACHER_GUID,
                school_id=school_a,
                upn="not-a-teacher@example.ch",
                kind="student",
                enabled=True,
            )
        )
        await db_session.commit()
        app.dependency_overrides[get_ad_client] = lambda: mock_ad_with_teachers
        try:
            r = await as_smi_a.post(
                f"/teachers/{TEACHER_GUID}/password-reset",
                json={"mode": "generate"},
            )
            assert r.status_code == 400
            assert r.json()["detail"] == "not_a_teacher"
        finally:
            app.dependency_overrides.pop(get_ad_client, None)


class TestSmiUserListing:
    """SMI must be able to list users from its assigned schools (cross-school via accumulation)."""

    @pytest.mark.asyncio
    async def test_smi_sees_users_in_assigned_school(
        self,
        as_smi_a: AsyncClient,
        db_session: AsyncSession,
        school_a: int,
    ) -> None:
        await _seed_teacher(db_session, school_a)
        r = await as_smi_a.get("/users")
        assert r.status_code == 200
        upns = [row["upn"] for row in r.json()["items"]]
        assert any(TEACHER_GUID[:6] in u for u in upns)

    @pytest.mark.asyncio
    async def test_smi_does_not_see_other_school(
        self,
        as_smi_a: AsyncClient,
        db_session: AsyncSession,
        school_b: int,
    ) -> None:
        await _seed_teacher(db_session, school_b, guid=OTHER_SCHOOL_TEACHER_GUID)
        r = await as_smi_a.get("/users")
        assert r.status_code == 200
        upns = [row["upn"] for row in r.json()["items"]]
        assert not any(OTHER_SCHOOL_TEACHER_GUID[:6] in u for u in upns)


# Silence unused-import lint when ASGITransport isn't used directly here.
_ = ASGITransport
