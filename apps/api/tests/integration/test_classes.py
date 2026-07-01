"""End-to-end CRUD for /classes — DoD coverage for issue #4."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from magister_api.models.audit import AuditEvent
from magister_api.models.school_class import (
    CLASS_STATUS_ACTIVE,
    CLASS_STATUS_ARCHIVED,
    SchoolClass,
)

if TYPE_CHECKING:
    from fastapi import FastAPI
    from sqlalchemy.ext.asyncio import AsyncSession

    from magister_api.config import Settings

pytestmark = pytest.mark.postgres


async def _get_actions(engine: AsyncEngine) -> list[str]:
    sm = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
    async with sm() as s:
        return list(
            (await s.execute(select(AuditEvent.action).order_by(AuditEvent.id))).scalars().all()
        )


class TestClassDetails:
    @pytest.mark.asyncio
    async def test_create_with_details_then_edit(
        self, as_schulleitung_a: AsyncClient, engine: AsyncEngine
    ) -> None:
        resp = await as_schulleitung_a.post(
            "/classes",
            json={"name": "4a", "jahrgangsstufe": 4, "details": "Raum 12"},
        )
        assert resp.status_code == 201, resp.text
        cid = resp.json()["id"]
        assert resp.json()["details"] == "Raum 12"

        # PATCH name + details together; relations (by id) stay intact.
        resp = await as_schulleitung_a.patch(
            f"/classes/{cid}",
            json={"name": "4a*", "details": "Raum 12 · Fokus Musik"},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["name"] == "4a*"
        assert resp.json()["details"] == "Raum 12 · Fokus Musik"

        # Audit recorded the edit, but never the free-text details content.
        sm = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
        async with sm() as s:
            rows = (
                (
                    await s.execute(
                        select(AuditEvent.action).where(AuditEvent.action == "class_renamed")
                    )
                )
                .scalars()
                .all()
            )
        assert len(rows) == 1


class TestSchulleitungCrud:
    @pytest.mark.asyncio
    async def test_create_lists_get_then_archive(
        self, as_schulleitung_a: AsyncClient, school_a: int, engine: AsyncEngine
    ) -> None:
        # Create
        resp = await as_schulleitung_a.post(
            "/classes", json={"name": "4a", "kuerzel": "K4A", "jahrgangsstufe": 4}
        )
        assert resp.status_code == 201, resp.text
        body = resp.json()
        cid = body["id"]
        assert body["school_id"] == school_a
        assert body["status"] == CLASS_STATUS_ACTIVE

        # List shows the new class
        resp = await as_schulleitung_a.get("/classes")
        assert resp.status_code == 200
        names = [c["name"] for c in resp.json()]
        assert names == ["4a"]

        # Get single
        resp = await as_schulleitung_a.get(f"/classes/{cid}")
        assert resp.status_code == 200
        assert resp.json()["name"] == "4a"

        # Rename
        resp = await as_schulleitung_a.patch(f"/classes/{cid}", json={"name": "4b"})
        assert resp.status_code == 200, resp.text
        assert resp.json()["name"] == "4b"

        # Archive (soft-delete)
        resp = await as_schulleitung_a.delete(f"/classes/{cid}")
        assert resp.status_code == 204

        # No longer in active list
        resp = await as_schulleitung_a.get("/classes")
        assert resp.status_code == 200
        assert resp.json() == []

        # But row still exists in DB with status='archived'
        sm = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
        async with sm() as s:
            row = await s.get(SchoolClass, cid)
            assert row is not None
            assert row.status == CLASS_STATUS_ARCHIVED
            assert row.name == "4b"

        # Audit trail
        actions = await _get_actions(engine)
        assert actions == ["class_created", "class_renamed", "class_archived"]


class TestCrossSchoolBlocked:
    @pytest.mark.asyncio
    async def test_schulleitung_a_cannot_create_in_school_b(
        self,
        as_schulleitung_a: AsyncClient,
        school_b: int,
    ) -> None:
        resp = await as_schulleitung_a.post(
            "/classes",
            json={
                "name": "5a",
                "kuerzel": "K5A",
                "jahrgangsstufe": 5,
                "school_id": school_b,
            },
        )
        assert resp.status_code == 403
        assert resp.json()["detail"] == "cross_school_write"

    @pytest.mark.asyncio
    async def test_schulleitung_a_cannot_see_school_b_classes(
        self,
        as_schulleitung_a: AsyncClient,
        as_schulleitung_b: AsyncClient,
        school_b: int,
        engine: AsyncEngine,
    ) -> None:
        # B creates a class in school B
        r = await as_schulleitung_b.post(
            "/classes", json={"name": "5b", "kuerzel": "K5B", "jahrgangsstufe": 5}
        )
        assert r.status_code == 201, r.text
        b_id = r.json()["id"]

        # A's listing must not include it
        r = await as_schulleitung_a.get("/classes")
        assert r.status_code == 200
        assert r.json() == []

        # A's GET by id must 404 (scope filter hides it)
        r = await as_schulleitung_a.get(f"/classes/{b_id}")
        assert r.status_code == 404

        # A's PATCH must 404
        r = await as_schulleitung_a.patch(f"/classes/{b_id}", json={"name": "5b-renamed"})
        assert r.status_code == 404

        # A's DELETE must 404 — and class B must still be active in DB
        r = await as_schulleitung_a.delete(f"/classes/{b_id}")
        assert r.status_code == 404

        sm = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
        async with sm() as s:
            row = await s.get(SchoolClass, b_id)
            assert row is not None
            assert row.status == CLASS_STATUS_ACTIVE


class TestAdmin:
    @pytest.mark.asyncio
    async def test_admin_can_write_into_any_school(
        self, as_admin: AsyncClient, school_a: int, school_b: int
    ) -> None:
        for sid in (school_a, school_b):
            r = await as_admin.post(
                "/classes",
                json={"name": f"3a-{sid}", "jahrgangsstufe": 3, "school_id": sid},
            )
            assert r.status_code == 201, r.text

        r = await as_admin.get("/classes")
        assert r.status_code == 200
        sids = {c["school_id"] for c in r.json()}
        assert sids == {school_a, school_b}

    @pytest.mark.asyncio
    async def test_admin_must_supply_school_id(self, as_admin: AsyncClient) -> None:
        r = await as_admin.post("/classes", json={"name": "x", "jahrgangsstufe": 3})
        assert r.status_code == 400
        assert r.json()["detail"] == "school_id_required_for_admin"


class TestAuthnAuthz:
    @pytest.mark.asyncio
    async def test_unauthenticated_blocked(self, client: AsyncClient, school_a: int) -> None:
        r = await client.get("/classes")
        assert r.status_code == 401

    @pytest.mark.asyncio
    async def test_csrf_required_on_post(
        self,
        app: FastAPI,
        app_settings: Settings,
        db_session: AsyncSession,
        school_a: int,
    ) -> None:
        """A session without an X-CSRF-Token header must be rejected on mutating methods."""
        from httpx import ASGITransport
        from httpx import AsyncClient as Cli

        from tests.integration._helpers import seed_user_with_session

        sid, _csrf = await seed_user_with_session(
            session=db_session,
            settings=app_settings,
            upn="sl-csrf@example.ch",
            ad_object_guid="00000000-0000-0000-0000-00000000c5cf",
            school_id=school_a,
            kind="teacher",
            role="schulleitung",
            role_school_id=school_a,
        )
        await db_session.commit()
        async with Cli(
            transport=ASGITransport(app=app),
            base_url="http://testserver",
            cookies={"magister_session": sid},
        ) as c:
            r = await c.post(
                "/classes",
                json={"name": "5a", "kuerzel": "K5A", "jahrgangsstufe": 5},
            )
            assert r.status_code == 403
            assert r.json()["detail"] in {"csrf_missing", "csrf_invalid", "csrf_mismatch"}


class TestActiveNameUniquenessReusable:
    @pytest.mark.asyncio
    async def test_can_recreate_after_archive(self, as_schulleitung_a: AsyncClient) -> None:
        """Archiving a class frees its name for re-use within the same school."""
        r = await as_schulleitung_a.post("/classes", json={"name": "4a", "jahrgangsstufe": 4})
        assert r.status_code == 201
        cid = r.json()["id"]
        r = await as_schulleitung_a.delete(f"/classes/{cid}")
        assert r.status_code == 204

        # Name is free again — partial unique index excludes archived rows.
        r = await as_schulleitung_a.post("/classes", json={"name": "4a", "jahrgangsstufe": 4})
        assert r.status_code == 201, r.text
        new_cid = r.json()["id"]
        assert new_cid != cid


class TestPatchNoOp:
    @pytest.mark.asyncio
    async def test_patch_without_changes_emits_no_audit(
        self, as_schulleitung_a: AsyncClient, engine: AsyncEngine
    ) -> None:
        r = await as_schulleitung_a.post("/classes", json={"name": "4a", "jahrgangsstufe": 4})
        assert r.status_code == 201
        cid = r.json()["id"]

        # PATCH with same name → no class_renamed event
        r = await as_schulleitung_a.patch(f"/classes/{cid}", json={"name": "4a"})
        assert r.status_code == 200

        actions = await _get_actions(engine)
        assert actions.count("class_renamed") == 0
        assert actions.count("class_created") == 1
