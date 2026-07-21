"""Teacher bulk-import must not be undone by a post-loop audit failure.

Regression for the reported symptom: teachers are created in AD but end up
missing from Magister and the UI shows a generic error. Root cause: the
post-loop ``import_applied`` summary emit ran with no savepoint, so an audit
failure there rolled back the whole request transaction — discarding every
``ad_user_cache`` row created during the loop while the AD accounts survived.
"""

from __future__ import annotations

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from magister_api.ad.client import AdClient
from magister_api.audit.service import AuditService
from magister_api.config import Settings
from magister_api.models.auth import AdUserCache
from magister_api.models.school import School
from magister_api.routers.imports import get_ad_client

pytestmark = pytest.mark.postgres

TEACHERS_HEADER = (
    "given_name,surname,display_name,upn,sam_account_name,force_change,"
    "cannot_change_password,password_never_expires"
)


@pytest.fixture
def mock_ad(app_settings: Settings) -> AdClient:
    return AdClient(app_settings.model_copy(update={"ad_use_mock": True}))


@pytest_asyncio.fixture(autouse=True)
async def _teacher_ou(db_session: AsyncSession, school_a: int) -> None:
    # Teacher OU is now per-school; configure every school in the fixture DB.
    for school in (await db_session.execute(select(School))).scalars().all():
        school.ad_ou_teachers = "OU=Lehrpersonen,DC=schule,DC=local"
    await db_session.commit()


@pytest.mark.asyncio
async def test_import_applied_audit_failure_keeps_teacher(
    as_smi_a: AsyncClient,
    app: FastAPI,
    db_session: AsyncSession,
    school_a: int,
    mock_ad: AdClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Make ONLY the post-loop summary event blow up (simulating an audit-infra
    # hiccup at encrypt time); per-row teacher_provisioned events still succeed.
    real_emit = AuditService.emit

    async def flaky_emit(self: AuditService, *, action: str, **kw: object) -> int:
        if action == "import_applied":
            raise RuntimeError("pgcrypto unavailable")
        return await real_emit(self, action=action, **kw)  # type: ignore[arg-type]

    monkeypatch.setattr(AuditService, "emit", flaky_emit)

    csv = f"{TEACHERS_HEADER}\nErika,Lehrer,,erika.lehrer@schule.ch,,true,,\n"
    r = await as_smi_a.post("/imports?kind=teachers", files={"file": ("t.csv", csv, "text/csv")})
    assert r.status_code == 201, r.text
    job_id = r.json()["id"]

    app.dependency_overrides[get_ad_client] = lambda: mock_ad
    try:
        r = await as_smi_a.post(f"/imports/{job_id}/apply")
    finally:
        app.dependency_overrides.pop(get_ad_client, None)

    # The apply must succeed despite the summary-audit failure...
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["summary"]["applied"]["created"] == 1
    assert body["summary"]["applied"]["failed"] == 0

    # ...and the provisioned teacher must be persisted in Magister.
    n = (
        await db_session.execute(
            select(func.count())
            .select_from(AdUserCache)
            .where(AdUserCache.upn == "erika.lehrer@schule.ch")
        )
    ).scalar_one()
    assert n == 1
