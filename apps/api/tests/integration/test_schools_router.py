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


class TestSchoolCrud:
    @pytest.mark.asyncio
    async def test_admin_creates_edits_and_reads_school(self, as_admin: AsyncClient) -> None:
        resp = await as_admin.post(
            "/schools",
            json={
                "name": "Primarschule Musterdorf",
                "kuerzel": "PSM",
                "scope_short": "PSM",
                "street": "Schulweg 1",
                "postal_code": "3000",
                "city": "Bern",
                "phone": "+41 31 000 00 00",
                "description": "Hauptgebäude",
                "latitude": 46.948,
                "longitude": 7.4474,
            },
        )
        assert resp.status_code == 201, resp.text
        body = resp.json()
        sid = body["id"]
        assert body["city"] == "Bern"
        assert body["latitude"] == 46.948

        # Read it back.
        resp = await as_admin.get(f"/schools/{sid}")
        assert resp.status_code == 200
        assert resp.json()["phone"] == "+41 31 000 00 00"

        # Patch a single field.
        resp = await as_admin.patch(f"/schools/{sid}", json={"phone": "+41 31 111 11 11"})
        assert resp.status_code == 200, resp.text
        assert resp.json()["phone"] == "+41 31 111 11 11"

        # Delete (no classes yet).
        resp = await as_admin.delete(f"/schools/{sid}")
        assert resp.status_code == 204
        assert (await as_admin.get(f"/schools/{sid}")).status_code == 404

    @pytest.mark.asyncio
    async def test_duplicate_kuerzel_conflicts(self, as_admin: AsyncClient) -> None:
        payload = {"name": "A", "kuerzel": "DUP", "scope_short": "DUP"}
        assert (await as_admin.post("/schools", json=payload)).status_code == 201
        resp = await as_admin.post("/schools", json={**payload, "name": "B"})
        assert resp.status_code == 409
        assert resp.json()["detail"] == "kuerzel_conflict"

    @pytest.mark.asyncio
    async def test_delete_refused_when_classes_exist(
        self, as_admin: AsyncClient, school_a: int
    ) -> None:
        # school_a has a class created below.
        await as_admin.post(
            "/classes", json={"name": "1a", "jahrgangsstufe": 1, "school_id": school_a}
        )
        resp = await as_admin.delete(f"/schools/{school_a}")
        assert resp.status_code == 409
        assert resp.json()["detail"] == "school_in_use"

    @pytest.mark.asyncio
    async def test_schulleitung_cannot_create(self, as_schulleitung_a: AsyncClient) -> None:
        resp = await as_schulleitung_a.post(
            "/schools", json={"name": "X", "kuerzel": "XX", "scope_short": "XX"}
        )
        assert resp.status_code == 403
