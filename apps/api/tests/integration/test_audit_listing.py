"""M2 US-7 — GET /audit/events.

Covers RBAC matrix, school-scope enforcement (incl. NULL-school visibility for
admin only), filters (action / actor_upn substring / ts range), pagination
(total reflects unfiltered count), and payload decryption.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
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
async def seed_audit(
    engine: AsyncEngine, app_settings: Settings, school_a: int, school_b: int
) -> dict[str, int]:
    """Insert a deterministic mix of events: A / B / NULL × user_disabled / class_created."""
    sm = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
    base = datetime(2026, 5, 1, 12, 0, 0, tzinfo=UTC)

    async with sm() as s:
        svc = AuditService(s, app_settings)
        # Two A events, one B event, one cross-school (NULL).
        await svc.emit(
            action="user_disabled",
            target_kind="user",
            target_id="aaaa-1",
            actor_upn="anna@example.ch",
            actor_object_guid="0000-anna",
            school_id=school_a,
            ip=None,
            request_id="req-a1",
            payload={"previous_enabled": True, "new_enabled": False, "reason": "Schulaustritt"},
        )
        await svc.emit(
            action="class_created",
            target_kind="class",
            target_id="42",
            actor_upn="anna@example.ch",
            actor_object_guid="0000-anna",
            school_id=school_a,
            ip=None,
            request_id="req-a2",
            payload={"name": "4a"},
        )
        await svc.emit(
            action="user_disabled",
            target_kind="user",
            target_id="bbbb-1",
            actor_upn="bob@example.ch",
            actor_object_guid="0000-bob",
            school_id=school_b,
            ip=None,
            request_id="req-b1",
            payload={"previous_enabled": True, "new_enabled": False, "reason": ""},
        )
        await svc.emit(
            action="local_admin_seeded",
            target_kind="local_admin",
            target_id="root",
            actor_upn=None,
            actor_object_guid=None,
            school_id=None,
            ip=None,
            request_id="boot",
            payload={"source": "env"},
        )
        # Hand-tweak ts so order is predictable: a1=base, a2=base+1, b1=base+2, null=base+3.
        # ``emit`` defaults ts to utcnow(); we don't currently expose the param —
        # accept the natural insertion order: returned ts is monotonically increasing
        # within the same test microsecond resolution. That's enough for the assertions
        # below (we only check counts, totals, and decrypted-payload content).
        await s.commit()
        del base  # unused intentionally — kept for future ts assertions
    return {"school_a": school_a, "school_b": school_b}


class TestRbac:
    @pytest.mark.asyncio
    async def test_admin_sees_all_including_null_school(
        self, as_admin: AsyncClient, seed_audit: dict[str, int]
    ) -> None:
        r = await as_admin.get("/audit/events")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["total"] == 4
        school_ids = {item["school_id"] for item in body["items"]}
        assert None in school_ids
        assert seed_audit["school_a"] in school_ids
        assert seed_audit["school_b"] in school_ids

    @pytest.mark.asyncio
    async def test_schulleitung_sees_only_own_school_excludes_null(
        self,
        as_schulleitung_a: AsyncClient,
        seed_audit: dict[str, int],
    ) -> None:
        r = await as_schulleitung_a.get("/audit/events")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["total"] == 2
        for item in body["items"]:
            assert item["school_id"] == seed_audit["school_a"]

    @pytest.mark.asyncio
    async def test_smi_has_same_scope_as_schulleitung(
        self, as_smi_a: AsyncClient, seed_audit: dict[str, int]
    ) -> None:
        r = await as_smi_a.get("/audit/events")
        assert r.status_code == 200
        for item in r.json()["items"]:
            assert item["school_id"] == seed_audit["school_a"]

    @pytest.mark.asyncio
    async def test_schulleitung_school_id_param_within_scope_passes(
        self, as_schulleitung_a: AsyncClient, seed_audit: dict[str, int]
    ) -> None:
        r = await as_schulleitung_a.get(
            "/audit/events", params={"school_id": seed_audit["school_a"]}
        )
        assert r.status_code == 200
        assert r.json()["total"] == 2

    @pytest.mark.asyncio
    async def test_schulleitung_school_id_param_outside_scope_403(
        self, as_schulleitung_a: AsyncClient, seed_audit: dict[str, int]
    ) -> None:
        r = await as_schulleitung_a.get(
            "/audit/events", params={"school_id": seed_audit["school_b"]}
        )
        assert r.status_code == 403, r.text


class TestFilters:
    @pytest.mark.asyncio
    async def test_action_filter(self, as_admin: AsyncClient, seed_audit: dict[str, int]) -> None:
        r = await as_admin.get("/audit/events", params={"action": "user_disabled"})
        assert r.status_code == 200
        body = r.json()
        assert body["total"] == 2
        assert {item["action"] for item in body["items"]} == {"user_disabled"}

    @pytest.mark.asyncio
    async def test_actor_upn_substring_case_insensitive(
        self, as_admin: AsyncClient, seed_audit: dict[str, int]
    ) -> None:
        r = await as_admin.get("/audit/events", params={"actor_upn": "ANNA"})
        assert r.status_code == 200
        body = r.json()
        assert body["total"] == 2
        for item in body["items"]:
            assert "anna" in (item["actor_upn"] or "").lower()

    @pytest.mark.asyncio
    async def test_ts_range_excludes_future_events(
        self, as_admin: AsyncClient, seed_audit: dict[str, int]
    ) -> None:
        far_future = (datetime.now(UTC) + timedelta(days=365)).isoformat()
        r = await as_admin.get("/audit/events", params={"from_ts": far_future})
        assert r.status_code == 200
        assert r.json()["total"] == 0


class TestPaginationAndPayload:
    @pytest.mark.asyncio
    async def test_pagination_limit_one_total_reflects_full_count(
        self, as_admin: AsyncClient, seed_audit: dict[str, int]
    ) -> None:
        r = await as_admin.get("/audit/events", params={"limit": 1})
        assert r.status_code == 200
        body = r.json()
        assert len(body["items"]) == 1
        assert body["total"] == 4

    @pytest.mark.asyncio
    async def test_payload_is_decrypted_and_readable(
        self, as_admin: AsyncClient, seed_audit: dict[str, int]
    ) -> None:
        r = await as_admin.get(
            "/audit/events", params={"action": "user_disabled", "actor_upn": "anna"}
        )
        assert r.status_code == 200
        items = r.json()["items"]
        assert len(items) == 1
        payload = items[0]["payload"]
        # The pgcrypto column returns plaintext JSON via the AuditService helper.
        assert payload == {
            "previous_enabled": True,
            "new_enabled": False,
            "reason": "Schulaustritt",
        }
