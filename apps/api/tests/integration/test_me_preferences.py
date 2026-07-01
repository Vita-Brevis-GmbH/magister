"""GET/PUT /me/preferences — self-service language/region/format settings."""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from magister_api.models.audit import AuditEvent

pytestmark = pytest.mark.postgres


@pytest.mark.asyncio
async def test_defaults_when_unset(as_schulleitung_a: AsyncClient) -> None:
    r = await as_schulleitung_a.get("/me/preferences")
    assert r.status_code == 200, r.text
    assert r.json() == {
        "language": "de",
        "region": "CH",
        "date_format": "DD.MM.YYYY",
        "time_format": "24h",
    }


@pytest.mark.asyncio
async def test_put_then_get_roundtrip(as_schulleitung_a: AsyncClient, engine: AsyncEngine) -> None:
    body = {"language": "fr", "region": "FR", "date_format": "YYYY-MM-DD", "time_format": "12h"}
    r = await as_schulleitung_a.put("/me/preferences", json=body)
    assert r.status_code == 200, r.text
    assert r.json() == body

    r = await as_schulleitung_a.get("/me/preferences")
    assert r.json() == body

    # Write is audited.
    sm = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
    async with sm() as s:
        actions = (await s.execute(select(AuditEvent.action))).scalars().all()
    assert "user_preferences_updated" in actions


@pytest.mark.asyncio
async def test_invalid_language_rejected(as_schulleitung_a: AsyncClient) -> None:
    r = await as_schulleitung_a.put(
        "/me/preferences",
        json={"language": "es", "region": "ES", "date_format": "DD.MM.YYYY", "time_format": "24h"},
    )
    assert r.status_code == 422
