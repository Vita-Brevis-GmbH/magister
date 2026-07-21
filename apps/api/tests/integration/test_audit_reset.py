"""POST /admin/audit/reset — clear the activity overview before hand-over."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
import pytest_asyncio
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from magister_api.audit.service import AuditService
from magister_api.config import Settings
from magister_api.models.import_job import ImportJob

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
        # Two import jobs that the reset must also clear.
        s.add(ImportJob(school_id=school_a, kind="students", status="applied", filename="a.csv"))
        s.add(ImportJob(school_id=school_a, kind="classes", status="staged", filename="b.csv"))
        await s.commit()


@pytest.mark.asyncio
async def test_reset_clears_all_and_records_itself(
    as_admin: AsyncClient, seed_events: None, engine: AsyncEngine
) -> None:
    before = (await as_admin.get("/audit/events")).json()
    assert before["total"] >= 3

    r = await as_admin.post("/admin/audit/reset")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["deleted"] >= 3
    assert body["imports_deleted"] == 2

    after = (await as_admin.get("/audit/events")).json()
    # Only the reset entry survives — it documents who cleared the log.
    assert after["total"] == 1
    assert after["items"][0]["action"] == "audit_reset"
    assert after["items"][0]["payload"]["deleted"] >= 3
    assert after["items"][0]["payload"]["imports_deleted"] == 2

    # The import history is now empty too.
    sm = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
    async with sm() as s:
        remaining = (await s.execute(select(func.count()).select_from(ImportJob))).scalar_one()
    assert remaining == 0


@pytest.mark.asyncio
async def test_reset_requires_admin(as_schulleitung_a: AsyncClient) -> None:
    r = await as_schulleitung_a.post("/admin/audit/reset")
    assert r.status_code == 403
