"""End-to-end ``POST /users/{guid}/password-reset`` — generic (company) reset."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

import pytest
import pytest_asyncio
from httpx import AsyncClient
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

COMPANY_GUID = "00000000-0000-0000-0000-0000000000c7"


def _le(g: str) -> bytes:
    return uuid.UUID(g).bytes_le


@pytest_asyncio.fixture
async def mock_ad_with_company_user(app_settings: Settings):
    settings = app_settings.model_copy(
        update={"ad_use_mock": True, "ad_users_search_base": "DC=firma,DC=local"}
    )
    client = AdClient(settings)
    conn = client.mock_connection()
    conn.strategy.add_entry(
        "CN=C1,OU=Benutzer,DC=firma,DC=local",
        {
            "objectClass": ["user"],
            "objectGUID": _le(COMPANY_GUID),
            "userPrincipalName": f"{COMPANY_GUID[:6]}@firma.ch",
            "userAccountControl": 0x200,
        },
    )
    yield client
    await client.aclose()


async def _seed_user(db_session: AsyncSession, school_id: int, kind: str = "company") -> None:
    db_session.add(
        AdUserCache(
            ad_object_guid=COMPANY_GUID,
            school_id=school_id,
            upn=f"{COMPANY_GUID[:6]}@firma.ch",
            kind=kind,
            enabled=True,
        )
    )
    await db_session.flush()
    await db_session.commit()


class TestHappyPath:
    @pytest.mark.asyncio
    async def test_admin_resets_company_user(
        self,
        app: FastAPI,
        as_admin: AsyncClient,
        app_settings: Settings,
        db_session: AsyncSession,
        school_a: int,
        engine: AsyncEngine,
        mock_ad_with_company_user: AdClient,
    ) -> None:
        await _seed_user(db_session, school_a)
        app.dependency_overrides[get_ad_client] = lambda: mock_ad_with_company_user
        try:
            r = await as_admin.post(
                f"/users/{COMPANY_GUID}/password-reset",
                json={"mode": "generate"},
            )
            assert r.status_code == 200, r.text
            body = r.json()
            assert body["mode"] == "generate"
            temp_pw = body["temp_password"]
            assert temp_pw and len(temp_pw) >= 12
        finally:
            app.dependency_overrides.pop(get_ad_client, None)

        # Audit emits ``user_password_reset`` and never the plaintext.
        sm = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
        async with sm() as s:
            row = (
                (
                    await s.execute(
                        select(AuditEvent)
                        .where(AuditEvent.action == "user_password_reset")
                        .order_by(AuditEvent.id.desc())
                    )
                )
                .scalars()
                .first()
            )
            assert row is not None
            event = await AuditService(s, app_settings).read(row.id)
        assert event is not None
        assert "temp_password" not in event.payload
        assert temp_pw not in repr(event.payload)


class TestGuards:
    @pytest.mark.asyncio
    async def test_teacher_is_rejected_here(
        self,
        app: FastAPI,
        as_admin: AsyncClient,
        db_session: AsyncSession,
        school_a: int,
        mock_ad_with_company_user: AdClient,
    ) -> None:
        # A teacher must use /teachers/... — the generic endpoint refuses.
        await _seed_user(db_session, school_a, kind="teacher")
        app.dependency_overrides[get_ad_client] = lambda: mock_ad_with_company_user
        try:
            r = await as_admin.post(
                f"/users/{COMPANY_GUID}/password-reset",
                json={"mode": "generate"},
            )
            assert r.status_code == 400
            assert r.json()["detail"] == "use_kind_specific_reset"
        finally:
            app.dependency_overrides.pop(get_ad_client, None)

    @pytest.mark.asyncio
    async def test_unauthenticated_blocked(self, app: FastAPI, client: AsyncClient) -> None:
        r = await client.post(
            f"/users/{COMPANY_GUID}/password-reset",
            json={"mode": "generate"},
        )
        assert r.status_code == 403
