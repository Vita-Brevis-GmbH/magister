"""GET /schools — scope-aware school listing for dropdowns."""

from __future__ import annotations

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.postgres


class TestListSchools:
    @pytest.mark.asyncio
    async def test_schulleitung_sees_only_own_school(
        self, as_schulleitung_a: AsyncClient, school_a: int, school_b: int
    ) -> None:
        r = await as_schulleitung_a.get("/schools")
        assert r.status_code == 200, r.text
        ids = [s["id"] for s in r.json()]
        assert ids == [school_a]

    @pytest.mark.asyncio
    async def test_admin_sees_all_schools(
        self, as_admin: AsyncClient, school_a: int, school_b: int
    ) -> None:
        r = await as_admin.get("/schools")
        assert r.status_code == 200
        ids = {s["id"] for s in r.json()}
        assert {school_a, school_b} <= ids
        # The payload carries human-friendly fields for the dropdown.
        sample = r.json()[0]
        assert {"id", "name", "kuerzel", "scope_short"} <= set(sample)
