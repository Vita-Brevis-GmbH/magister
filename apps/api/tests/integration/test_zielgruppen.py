"""Zielgruppen: Standardgruppen je Schule, Passwortart, Konto-Vorgaben, Tresor.

Skipped unless MAGISTER_TEST_DATABASE_URL is set (see integration conftest).
"""

from __future__ import annotations

import re
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING, Any

import pytest
import pytest_asyncio
from sqlalchemy import select

from magister_api.ad.client import AdClient
from magister_api.config import Settings
from magister_api.models.app_settings import AppSettings
from magister_api.models.auth import AdUserCache
from magister_api.models.group_template import GroupTemplate
from magister_api.models.school import School
from magister_api.routers.admin_sync import get_ad_client
from magister_api.services.password_vault import PasswordVaultService
from magister_api.services.zielgruppen import password_profile_for

if TYPE_CHECKING:
    from fastapi import FastAPI
    from httpx import AsyncClient
    from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.postgres

SEARCH_BASE = "DC=schule,DC=local"
READABLE = re.compile(r"^[A-Z][a-z]+-[A-Z][a-z]+-\d{2,}$")


@pytest_asyncio.fixture
async def mock_ad(app_settings: Settings) -> AsyncIterator[AdClient]:
    client = AdClient(
        app_settings.model_copy(update={"ad_use_mock": True, "ad_users_search_base": SEARCH_BASE})
    )
    yield client
    await client.aclose()


async def _ous(session: AsyncSession, school_id: int) -> None:
    school = await session.get(School, school_id)
    assert school is not None
    school.ad_ou_teachers = "OU=Lehrer,DC=schule,DC=local"
    school.ad_ou_students_other = "OU=Prim,DC=schule,DC=local"
    school.ad_ou_students_zyklus3 = "OU=Sek,DC=schule,DC=local"
    school.ad_groups_student_zyklus1 = ["CN=Z1,DC=schule,DC=local"]
    await session.commit()


async def _vault(session: AsyncSession, on: bool) -> None:
    row = await session.get(AppSettings, 1)
    assert row is not None
    row.password_store_enabled = on
    await session.commit()


async def _defaults(as_admin: AsyncClient, school_id: int) -> dict[str, dict[str, Any]]:
    r = await as_admin.post("/admin/group-templates/defaults", json={"school_id": school_id})
    assert r.status_code == 200, r.text
    return {t["kind"]: t for t in r.json()}


@pytest.mark.asyncio
async def test_defaults_are_created_once_with_their_options(
    as_admin: AsyncClient, db_session: AsyncSession, school_a: int
) -> None:
    await _ous(db_session, school_a)
    created = await _defaults(as_admin, school_a)
    assert set(created) == {"student_zyklus1", "student_zyklus2", "student_zyklus3", "teacher"}
    z1 = created["student_zyklus1"]
    assert z1["password_profile"] == "readable"
    assert z1["cannot_change_password"] is True and z1["force_change"] is False
    assert z1["store_password"] is True
    # Die Gruppen kommen aus der Standort-Konfiguration.
    assert z1["ad_groups"] == ["CN=Z1,DC=schule,DC=local"]
    assert created["student_zyklus3"]["force_change"] is True
    assert created["teacher"]["password_profile"] == "teacher"
    # Zweiter Aufruf: alles da, nichts Neues.
    assert await _defaults(as_admin, school_a) == {}


@pytest.mark.asyncio
async def test_new_school_gets_default_zielgruppen(as_admin: AsyncClient) -> None:
    r = await as_admin.post(
        "/schools", json={"name": "Neu", "kuerzel": "NEU", "scope_short": "NEU"}
    )
    assert r.status_code == 201, r.text
    sid = r.json()["id"]
    kinds = {
        t["kind"] for t in (await as_admin.get(f"/admin/group-templates?school_id={sid}")).json()
    }
    assert {"student_zyklus1", "student_zyklus2", "student_zyklus3", "teacher"} <= kinds


@pytest.mark.asyncio
async def test_deleting_a_school_archives_its_own_zielgruppen(
    as_admin: AsyncClient, db_session: AsyncSession
) -> None:
    sid = (
        await as_admin.post(
            "/schools", json={"name": "Weg", "kuerzel": "WEG", "scope_short": "WEG"}
        )
    ).json()["id"]
    own = [
        t["id"]
        for t in (await as_admin.get(f"/admin/group-templates?school_id={sid}")).json()
        if t["school_ids"] == [sid]
    ]
    assert len(own) == 4
    assert (await as_admin.delete(f"/schools/{sid}")).status_code == 204
    # Ohne Archivierung wären sie jetzt global und an jedem Standort angeboten.
    statuses = (
        await db_session.execute(select(GroupTemplate.status).where(GroupTemplate.id.in_(own)))
    ).scalars()
    assert set(statuses) == {"archived"}


@pytest.mark.asyncio
async def test_student_from_zielgruppe_gets_readable_password_and_vault(
    as_admin: AsyncClient,
    app: FastAPI,
    app_settings: Settings,
    mock_ad: AdClient,
    db_session: AsyncSession,
    school_a: int,
) -> None:
    await _ous(db_session, school_a)
    await _vault(db_session, True)
    z1 = (await _defaults(as_admin, school_a))["student_zyklus1"]
    app.dependency_overrides[get_ad_client] = lambda: mock_ad
    r = await as_admin.post(
        "/ad/users",
        json={
            "given_name": "Lia",
            "surname": "Klein",
            "sam_account_name": "lklein",
            "user_principal_name": "lia.klein@schule.ch",
            # Die Zielgruppe übersteuert ou_key.
            "ou_key": "teacher",
            "school_id": school_a,
            "group_template_id": z1["id"],
        },
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert READABLE.match(body["temp_password"]), body["temp_password"]
    assert body["force_change"] is False
    row = await db_session.get(AdUserCache, body["ad_object_guid"])
    assert row is not None
    await db_session.refresh(row)
    assert row.kind == "student"
    assert row.cannot_change_password is True
    assert row.group_template_id == z1["id"]
    assert row.store_password is True
    vault = PasswordVaultService(db_session, app_settings)
    assert await vault.get(row.ad_object_guid) == body["temp_password"]
    # Ein späterer Reset nimmt dieselbe Passwortart.
    assert await password_profile_for(db_session, row) == "readable"


@pytest.mark.asyncio
async def test_explicit_flag_beats_zielgruppe_and_no_vault_when_switch_off(
    as_admin: AsyncClient,
    app: FastAPI,
    mock_ad: AdClient,
    db_session: AsyncSession,
    school_a: int,
) -> None:
    await _ous(db_session, school_a)
    await _vault(db_session, False)
    z1 = (await _defaults(as_admin, school_a))["student_zyklus1"]
    app.dependency_overrides[get_ad_client] = lambda: mock_ad
    r = await as_admin.post(
        "/ad/users",
        json={
            "given_name": "Ben",
            "surname": "Klein",
            "sam_account_name": "bklein",
            "user_principal_name": "ben.klein@schule.ch",
            "ou_key": "student_zyklus1",
            "school_id": school_a,
            "group_template_id": z1["id"],
            "force_change": True,
        },
    )
    assert r.status_code == 201, r.text
    assert r.json()["force_change"] is True
    row = await db_session.get(AdUserCache, r.json()["ad_object_guid"])
    assert row is not None
    await db_session.refresh(row)
    assert row.store_password is False and row.password_enc is None


@pytest.mark.asyncio
async def test_student_without_zielgruppe_gets_readable_teacher_does_not(
    as_admin: AsyncClient,
    app: FastAPI,
    mock_ad: AdClient,
    db_session: AsyncSession,
    school_a: int,
) -> None:
    # Der eigentliche Fehler: vorher bekam jedes einzeln angelegte Konto das
    # komplexe 14-stellige Passwort, auch Kinder.
    await _ous(db_session, school_a)
    app.dependency_overrides[get_ad_client] = lambda: mock_ad
    base = {"school_id": school_a, "given_name": "Kim", "surname": "Test"}
    student = await as_admin.post(
        "/ad/users",
        json=base
        | {
            "sam_account_name": "ktest",
            "user_principal_name": "kim.test@schule.ch",
            "ou_key": "student_zyklus2",
        },
    )
    assert student.status_code == 201, student.text
    assert READABLE.match(student.json()["temp_password"])
    teacher = await as_admin.post(
        "/ad/users",
        json=base
        | {
            "sam_account_name": "ktest2",
            "user_principal_name": "kim.test2@schule.ch",
            "ou_key": "teacher",
        },
    )
    assert teacher.status_code == 201, teacher.text
    assert not READABLE.match(teacher.json()["temp_password"])
    assert len(teacher.json()["temp_password"]) == 12


@pytest.mark.asyncio
async def test_single_handout_is_one_pdf_and_admin_only(
    as_admin: AsyncClient, as_schulleitung_a: AsyncClient
) -> None:
    body = {
        "credentials": [
            {
                "upn": "lia.klein@schule.ch",
                "sam_account_name": "lklein",
                "display_name": "Lia Klein",
                "class_name": "1a",
                "password": "Tiger-Wolke-47",
                "force_change": False,
            }
        ],
        "school_name": "Schule A",
        "language": "de",
        "audience": "students",
    }
    r = await as_admin.post("/ad/users/handout", json=body)
    assert r.status_code == 200, r.text
    assert r.headers["content-type"] == "application/pdf"
    assert r.content.startswith(b"%PDF")
    assert (await as_schulleitung_a.post("/ad/users/handout", json=body)).status_code == 403
    assert (
        await as_admin.post("/ad/users/handout", json=body | {"credentials": []})
    ).status_code == 400


async def _create(
    as_admin: AsyncClient, school_id: int, sam: str, template_id: int | None, ou_key: str
) -> str:
    r = await as_admin.post(
        "/ad/users",
        json={
            "given_name": "Kim",
            "surname": sam,
            "sam_account_name": sam,
            "user_principal_name": f"{sam}@schule.ch",
            "ou_key": ou_key,
            "school_id": school_id,
            "group_template_id": template_id,
        },
    )
    assert r.status_code == 201, r.text
    return str(r.json()["ad_object_guid"])


async def _zyklus_groups(session: AsyncSession, school_id: int) -> None:
    school = await session.get(School, school_id)
    assert school is not None
    school.ad_groups_student_zyklus2 = ["CN=Z2,DC=schule,DC=local"]
    school.ad_groups_student_zyklus3 = ["CN=Z3,DC=schule,DC=local"]
    school.ad_groups_teacher = ["CN=LP,DC=schule,DC=local"]
    await session.commit()


@pytest.mark.asyncio
async def test_assign_swaps_the_groups_of_the_previous_zielgruppe(
    as_admin: AsyncClient,
    app: FastAPI,
    mock_ad: AdClient,
    db_session: AsyncSession,
    school_a: int,
) -> None:
    await _ous(db_session, school_a)
    await _zyklus_groups(db_session, school_a)
    tpls = await _defaults(as_admin, school_a)
    app.dependency_overrides[get_ad_client] = lambda: mock_ad
    guid = await _create(
        as_admin, school_a, "kz2", int(tpls["student_zyklus2"]["id"]), "student_zyklus2"
    )
    # Zusätzlich eine Gruppe von Hand: sie gehört keiner Zielgruppe und bleibt.
    row = await db_session.get(AdUserCache, guid)
    assert row is not None
    row.ad_groups = ["CN=Z2,DC=schule,DC=local", "CN=Tool-X,DC=schule,DC=local"]
    await db_session.commit()

    z3 = tpls["student_zyklus3"]
    r = await as_admin.post(
        f"/admin/group-templates/{z3['id']}/assign", json={"ad_object_guids": [guid]}
    )
    assert r.status_code == 200, r.text
    (res,) = r.json()
    assert res["ok"] is True
    assert res["removed"] == ["CN=Z2,DC=schule,DC=local"]
    assert res["added"] == ["CN=Z3,DC=schule,DC=local"]
    assert res["ou_unchanged"] is False
    await db_session.refresh(row)
    assert row.group_template_id == z3["id"]
    # Zyklus 3 ändert selbst: die Einstellungen der Zielgruppe sind übernommen.
    assert row.cannot_change_password is False
    assert row.password_never_expires is False
    assert row.store_password is False


@pytest.mark.asyncio
async def test_assign_without_known_zielgruppe_drops_standard_groups_only(
    as_admin: AsyncClient,
    app: FastAPI,
    mock_ad: AdClient,
    db_session: AsyncSession,
    school_a: int,
) -> None:
    await _ous(db_session, school_a)
    await _zyklus_groups(db_session, school_a)
    tpls = await _defaults(as_admin, school_a)
    app.dependency_overrides[get_ad_client] = lambda: mock_ad
    guid = await _create(as_admin, school_a, "legacy", None, "student_zyklus2")
    row = await db_session.get(AdUserCache, guid)
    assert row is not None
    # Altes Konto: keine Zielgruppe bekannt.
    row.group_template_id = None
    row.ad_groups = ["CN=Z2,DC=schule,DC=local", "CN=Tool-X,DC=schule,DC=local"]
    await db_session.commit()

    r = await as_admin.post(
        f"/admin/group-templates/{tpls['teacher']['id']}/assign",
        json={"ad_object_guids": [guid], "apply_settings": False},
    )
    (res,) = r.json()
    assert res["ok"] is True
    assert res["removed"] == ["CN=Z2,DC=schule,DC=local"]
    assert res["added"] == ["CN=LP,DC=schule,DC=local"]
    # Lehrperson-Zielgruppe auf ein Schülerkonto: die OU bleibt, das wird gesagt.
    assert res["ou_unchanged"] is True


@pytest.mark.asyncio
async def test_assign_reports_per_account_errors_and_needs_admin(
    as_admin: AsyncClient,
    as_schulleitung_a: AsyncClient,
    db_session: AsyncSession,
    school_a: int,
    school_b: int,
) -> None:
    tpls = await _defaults(as_admin, school_a)
    tid = tpls["teacher"]["id"]
    db_session.add(
        AdUserCache(
            ad_object_guid="00000000-0000-0000-0000-0000000000b1",
            upn="b@schule.ch",
            kind="teacher",
            enabled=True,
            school_id=school_b,
        )
    )
    await db_session.commit()
    r = await as_admin.post(
        f"/admin/group-templates/{tid}/assign",
        json={
            "ad_object_guids": [
                "00000000-0000-0000-0000-0000000000b1",
                "00000000-0000-0000-0000-00000000dead",
            ]
        },
    )
    assert r.status_code == 200, r.text
    errors = {x["ad_object_guid"][-4:]: x["error"] for x in r.json()}
    assert errors == {"00b1": "not_for_school", "dead": "user_not_found"}
    denied = await as_schulleitung_a.post(
        f"/admin/group-templates/{tid}/assign",
        json={"ad_object_guids": ["00000000-0000-0000-0000-0000000000b1"]},
    )
    assert denied.status_code == 403
    assert (
        await as_admin.post(
            "/admin/group-templates/999999/assign",
            json={"ad_object_guids": ["00000000-0000-0000-0000-0000000000b1"]},
        )
    ).status_code == 404
