"""POST /admin/audit/reset — clear the activity overview before hand-over."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker

from magister_api.audit.service import AuditService
from magister_api.config import Settings

if TYPE_CHECKING:
    from httpx import AsyncClient
    from sqlalchemy.ext.asyncio import AsyncEngine

pytestmark = pytest.mark.postgres


@pytest_asyncio.fixture
async def seed_events(engine: AsyncEngine, app_settings: Settings, school_a: int) -> None:
    sm = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
    async with sm() as s:
        svc = AuditService(s, app_settings)
        for i in range(3):
            await svc.emit(
                action="user_disabled",
                target_kind="user",
                target_id=f"u{i}",
                actor_upn="anna@example.ch",
                actor_object_guid=None,
                school_id=school_a,
                ip=None,
                request_id=f"req-{i}",
                payload={},
            )
        await s.commit()


@pytest.mark.asyncio
async def test_reset_clears_all_and_records_itself(
    as_admin: AsyncClient, seed_events: None
) -> None:
    before = (await as_admin.get("/audit/events")).json()
    assert before["total"] >= 3

    r = await as_admin.post("/admin/audit/reset")
    assert r.status_code == 200, r.text
    assert r.json()["deleted"] >= 3

    after = (await as_admin.get("/audit/events")).json()
    # Only the reset entry survives — it documents who cleared the log.
    assert after["total"] == 1
    assert after["items"][0]["action"] == "audit_reset"
    assert after["items"][0]["payload"]["deleted"] >= 3


@pytest.mark.asyncio
async def test_reset_requires_admin(as_schulleitung_a: AsyncClient) -> None:
    r = await as_schulleitung_a.post("/admin/audit/reset")
    assert r.status_code == 403
