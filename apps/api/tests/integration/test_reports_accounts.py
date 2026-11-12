"""Reports: Konten je Zielgruppe und je Kontoart, im Sichtbereich."""

from __future__ import annotations

from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from magister_api.models.auth import AdUserCache
from magister_api.models.base import utcnow
from magister_api.models.group_template import GroupTemplate

pytestmark = pytest.mark.postgres


def _guid(n: int) -> str:
    return f"00000000-0000-0000-0000-0000000e{n:04d}"


async def _seed(db: AsyncSession, school_a: int, school_b: int) -> int:
    z1 = GroupTemplate(name="Zyklus 1", kind="student_zyklus1", ad_groups=[])
    db.add(z1)
    await db.flush()
    people: list[tuple[int, str, int | None, dict[str, Any]]] = [
        (school_a, "student", z1.id, {"store_password": True}),
        (school_a, "student", z1.id, {"enabled": False}),
        (school_a, "student", None, {"ad_missing_since": utcnow()}),
        (school_a, "teacher", None, {}),
        (school_b, "student", z1.id, {}),  # fremder Standort
    ]
    for i, (school, kind, tpl, extra) in enumerate(people, start=1):
        db.add(
            AdUserCache(
                ad_object_guid=_guid(i),
                school_id=school,
                upn=f"r{i}@schule.ch",
                kind=kind,
                enabled=extra.pop("enabled", True),
                group_template_id=tpl,
                **extra,
            )
        )
    await db.commit()
    return z1.id


@pytest.mark.asyncio
async def test_accounts_by_zielgruppe_and_kind_in_scope(
    as_schulleitung_a: AsyncClient, db_session: AsyncSession, school_a: int, school_b: int
) -> None:
    z1 = await _seed(db_session, school_a, school_b)

    r = await as_schulleitung_a.get("/reports/accounts-by-zielgruppe")
    assert r.status_code == 200, r.text
    body = r.json()
    by_tpl = {row["group_template_id"]: row for row in body["rows"]}
    assert by_tpl[z1] == {
        "group_template_id": z1,
        "name": "Zyklus 1",
        "kind": "student_zyklus1",
        "total": 2,
        "enabled": 1,
        "disabled": 1,
        "stored_password": 1,
    }
    # Ohne Zielgruppe: zwei aus dem Seed + das Konto der Schulleitung selbst.
    assert by_tpl[None]["total"] == 3
    assert body["total"] == 5  # Schule B zählt nicht
    assert body["rows"][-1]["group_template_id"] is None  # "ohne" zuletzt

    r = await as_schulleitung_a.get("/reports/accounts-by-kind")
    assert r.status_code == 200, r.text
    by_kind = {row["kind"]: row for row in r.json()["rows"]}
    assert by_kind["student"] == {
        "kind": "student",
        "total": 3,
        "enabled": 2,
        "disabled": 1,
        "stored_password": 1,
        "without_zielgruppe": 1,
        "missing_in_ad": 1,
    }
    assert by_kind["teacher"]["total"] == 2  # inkl. Schulleitung


@pytest.mark.asyncio
async def test_account_reports_need_login(client: AsyncClient) -> None:
    for path in ("/reports/accounts-by-zielgruppe", "/reports/accounts-by-kind"):
        assert (await client.get(path)).status_code == 401
