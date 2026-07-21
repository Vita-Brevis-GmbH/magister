"""Zyklus AD-group re-assignment when a student's grade year changes."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

from magister_api.config import Settings
from magister_api.models.app_settings import AppSettings
from magister_api.models.auth import AdUserCache
from magister_api.models.school import School
from magister_api.services.group_reassign import GradeChange, reassign_cycle_groups

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine

pytestmark = pytest.mark.postgres

Z1 = "CN=Z1,OU=g,DC=schule,DC=ch"
Z2 = "CN=Z2,OU=g,DC=schule,DC=ch"
Z3 = "CN=Z3,OU=g,DC=schule,DC=ch"
SHARED = "CN=Shared,OU=g,DC=schule,DC=ch"
GUID = "00000000-0000-0000-0000-00000000e001"


class FakeAd:
    """Records the group writes instead of talking to a real DC."""

    def __init__(self) -> None:
        self.added: list[str] = []
        self.removed: list[str] = []

    async def find_user_dn(self, ad_object_guid: str) -> str:
        return f"CN={ad_object_guid},OU=Students,DC=schule,DC=ch"

    async def add_user_to_groups(self, *, user_dn: str, group_dns: list[str]) -> list[str]:
        self.added.extend(group_dns)
        return []  # nothing failed

    async def remove_user_from_groups(self, *, user_dn: str, group_dns: list[str]) -> list[str]:
        self.removed.extend(group_dns)
        return []


async def _seed(
    engine: AsyncEngine, school_id: int, *, start_grade: int, groups: list[str]
) -> None:
    sm = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
    async with sm() as s:
        app = await s.get(AppSettings, 1)
        if app is None:
            app = AppSettings(id=1)
            s.add(app)
        app.zyklus1_max_grade = 2
        app.zyklus2_max_grade = 6
        # Zyklus boundaries stay global; group templates are per-school.
        school = await s.get(School, school_id)
        assert school is not None
        school.ad_groups_student_zyklus1 = [Z1, SHARED]
        school.ad_groups_student_zyklus2 = [Z2, SHARED]
        school.ad_groups_student_zyklus3 = [Z3, SHARED]
        s.add(
            AdUserCache(
                ad_object_guid=GUID,
                upn="kid@schule.ch",
                sam_account_name="kid",
                display_name="Kid",
                kind="student",
                enabled=True,
                school_id=school_id,
                jahrgangsstufe=start_grade,
                ad_groups=list(groups),
            )
        )
        await s.commit()


@pytest.mark.asyncio
async def test_crossing_zyklus_swaps_groups_and_keeps_manual(
    engine: AsyncEngine, app_settings: Settings, school_a: int
) -> None:
    # Grade 2 (Zyklus 1) → grade 3 (Zyklus 2). Student also has a manual group.
    manual = "CN=Chess,OU=g,DC=schule,DC=ch"
    await _seed(engine, school_a, start_grade=2, groups=[Z1, SHARED, manual])
    fake = FakeAd()
    sm = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
    async with sm() as s:
        n = await reassign_cycle_groups(
            s,
            app_settings,
            fake,  # type: ignore[arg-type]
            [GradeChange(ad_object_guid=GUID, old_grade=2, new_grade=3)],
            actor_upn="admin@example.ch",
            actor_object_guid=None,
            ip=None,
            request_id="req-1",
        )
        await s.commit()
        assert n == 1

    # Z1 removed, Z2 added; SHARED (in both templates) untouched; manual kept.
    assert fake.added == [Z2]
    assert fake.removed == [Z1]
    async with sm() as s:
        row = await s.get(AdUserCache, GUID)
        assert row is not None
        assert set(row.ad_groups) == {Z2, SHARED, manual}


@pytest.mark.asyncio
async def test_same_zyklus_is_noop(
    engine: AsyncEngine, app_settings: Settings, school_a: int
) -> None:
    # Grade 3 → grade 4 are both Zyklus 2 → no group writes at all.
    await _seed(engine, school_a, start_grade=3, groups=[Z2, SHARED])
    fake = FakeAd()
    sm = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
    async with sm() as s:
        n = await reassign_cycle_groups(
            s,
            app_settings,
            fake,  # type: ignore[arg-type]
            [GradeChange(ad_object_guid=GUID, old_grade=3, new_grade=4)],
            actor_upn="admin@example.ch",
            actor_object_guid=None,
            ip=None,
            request_id="req-2",
        )
        await s.commit()
    assert n == 0
    assert fake.added == []
    assert fake.removed == []


@pytest.mark.asyncio
async def test_no_ad_client_is_noop(
    engine: AsyncEngine, app_settings: Settings, school_a: int
) -> None:
    await _seed(engine, school_a, start_grade=2, groups=[Z1])
    sm = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
    async with sm() as s:
        n = await reassign_cycle_groups(
            s,
            app_settings,
            None,
            [GradeChange(ad_object_guid=GUID, old_grade=2, new_grade=8)],
            actor_upn="admin@example.ch",
            actor_object_guid=None,
            ip=None,
            request_id="req-3",
        )
    assert n == 0
