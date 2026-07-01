"""POST /admin/ad-test — read-only service-account connectivity probe."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from httpx import AsyncClient

from magister_api.ad.client import AdClient
from magister_api.config import Settings
from magister_api.routers.admin_sync import get_ad_client

pytestmark = pytest.mark.postgres


@pytest.fixture
def mock_ad(app_settings: Settings) -> AdClient:
    return AdClient(app_settings.model_copy(update={"ad_use_mock": True}))


@pytest.mark.asyncio
async def test_ad_test_reports_ok(as_admin: AsyncClient, app: FastAPI, mock_ad: AdClient) -> None:
    app.dependency_overrides[get_ad_client] = lambda: mock_ad
    try:
        r = await as_admin.post("/admin/ad-test")
        assert r.status_code == 200, r.text
        assert r.json() == {"ok": True, "detail": "ad_ok"}
    finally:
        app.dependency_overrides.pop(get_ad_client, None)


@pytest.mark.asyncio
async def test_ad_test_requires_admin(as_schulleitung_a: AsyncClient) -> None:
    r = await as_schulleitung_a.post("/admin/ad-test")
    assert r.status_code == 403
