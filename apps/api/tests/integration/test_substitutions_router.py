"""End-to-end /substitutions — school-scoped listing + revoke by role_id.

Complements test_class_teachers.py (which covers assignment via
/classes/{id}/teachers); here the focus is the cross-class substitution
view and its scope filter.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from magister_api.models.audit import AuditEvent
from magister_api.models.auth import AdUserCache
from magister_api.models.class_teacher_role import ClassTeacherRole

pytestmark = pytest.mark.postgres

STV_GUID = "00000000-0000-0000-0000-0000000000d4"


def _iso(dt: datetime) -> str:
    return dt.isoformat()


async def _create_class(client: AsyncClient, name: str = "4a") -> int:
    r = await client.post("/classes", json={"name": name, "jahrgangsstufe": 4})
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def _assign_stellvertretung(client: AsyncClient, class_id: int, guid: str = STV_GUID) -> int:
    r = await client.post(
        f"/classes/{class_id}/teachers",
        json={
            "ad_object_guid": guid,
            "role": "stellvertretung",
            "valid_from": _iso(datetime.now(UTC)),
        },
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def _seed_ad_user(
    session: AsyncSession, *, guid: str, school_id: int, upn: str, display_name: str
) -> None:
    session.add(
        AdUserCache(
            ad_object_guid=guid,
            school_id=school_id,
            upn=upn,
            given_name="Sven",
            surname="Stellvertreter",
            display_name=display_name,
            kind="teacher",
            enabled=True,
            last_sync_at=None,
            ms_ds_consistency_guid=guid,
        )
    )
    await session.commit()


class TestList:
    @pytest.mark.asyncio
    async def test_list_returns_substitution_in_scope(self, as_schulleitung_a: AsyncClient) -> None:
        cid = await _create_class(as_schulleitung_a)
        await _assign_stellvertretung(as_schulleitung_a, cid)

        r = await as_schulleitung_a.get("/substitutions")
        assert r.status_code == 200, r.text
        rows = r.json()
        assert len(rows) == 1
        assert rows[0]["ad_object_guid"] == STV_GUID
        assert rows[0]["class_id"] == cid
        assert rows[0]["class_name"] == "4a"
        assert rows[0]["role"] == "stellvertretung"

    @pytest.mark.asyncio
    async def test_list_enriches_user_label(
        self, as_schulleitung_a: AsyncClient, db_session: AsyncSession, school_a: int
    ) -> None:
        cid = await _create_class(as_schulleitung_a)
        await _assign_stellvertretung(as_schulleitung_a, cid)
        await _seed_ad_user(
            db_session,
            guid=STV_GUID,
            school_id=school_a,
            upn="sven.stv@example.ch",
            display_name="Sven Stellvertreter",
        )

        r = await as_schulleitung_a.get("/substitutions")
        assert r.status_code == 200
        row = r.json()[0]
        assert row["display_name"] == "Sven Stellvertreter"
        assert row["upn"] == "sven.stv@example.ch"

    @pytest.mark.asyncio
    async def test_list_scoped_to_own_school(
        self, as_schulleitung_a: AsyncClient, as_schulleitung_b: AsyncClient
    ) -> None:
        cid = await _create_class(as_schulleitung_a)
        await _assign_stellvertretung(as_schulleitung_a, cid)

        # B is in another school and must not see A's substitution.
        r = await as_schulleitung_b.get("/substitutions")
        assert r.status_code == 200
        assert r.json() == []

    @pytest.mark.asyncio
    async def test_admin_sees_all_schools(
        self, as_schulleitung_a: AsyncClient, as_admin: AsyncClient
    ) -> None:
        cid = await _create_class(as_schulleitung_a)
        await _assign_stellvertretung(as_schulleitung_a, cid)

        r = await as_admin.get("/substitutions")
        assert r.status_code == 200
        assert {row["ad_object_guid"] for row in r.json()} == {STV_GUID}


class TestRevoke:
    @pytest.mark.asyncio
    async def test_revoke_by_role_id(
        self, as_schulleitung_a: AsyncClient, engine: AsyncEngine
    ) -> None:
        cid = await _create_class(as_schulleitung_a)
        rid = await _assign_stellvertretung(as_schulleitung_a, cid)

        r = await as_schulleitung_a.delete(f"/substitutions/{rid}")
        assert r.status_code == 204

        sm = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
        async with sm() as s:
            row = await s.get(ClassTeacherRole, rid)
            assert row is not None
            assert row.valid_to is not None  # soft-deleted, not removed
            actions = list(
                (await s.execute(select(AuditEvent.action).order_by(AuditEvent.id))).scalars().all()
            )
        assert "class_teacher_revoked" in actions

    @pytest.mark.asyncio
    async def test_revoke_unknown_role_id_404(self, as_schulleitung_a: AsyncClient) -> None:
        r = await as_schulleitung_a.delete("/substitutions/9999")
        assert r.status_code == 404
        assert r.json()["detail"] == "class_teacher_role_not_found"

    @pytest.mark.asyncio
    async def test_revoke_cross_school_forbidden(
        self, as_schulleitung_a: AsyncClient, as_schulleitung_b: AsyncClient
    ) -> None:
        cid = await _create_class(as_schulleitung_a)
        rid = await _assign_stellvertretung(as_schulleitung_a, cid)

        # B may not revoke a role on A's class — the class is out of B's scope.
        r = await as_schulleitung_b.delete(f"/substitutions/{rid}")
        assert r.status_code == 403
