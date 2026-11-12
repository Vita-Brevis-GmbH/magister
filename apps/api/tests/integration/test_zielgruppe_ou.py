"""Ziel-OU einer Zielgruppe ohne feste Kontoart.

Gesetzt: neue Konten landen dort (Einzel-Anlage und CSV-Import). Leer: die OU
des Standorts. Bei fester Kontoart wird sie nicht gespeichert. Liegt sie nicht
im Standort, wird die Anlage abgelehnt — der AD-Abgleich ordnete das Konto
sonst keinem Standort zu.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from magister_api.ad.client import AdClient
from magister_api.config import Settings
from magister_api.models.school import School
from magister_api.routers.admin_sync import get_ad_client
from magister_api.routers.imports import get_ad_client as imports_ad_client

pytestmark = pytest.mark.postgres

GUEST_OU = "OU=Gaeste,OU=A,DC=schule,DC=local"


@pytest_asyncio.fixture
async def mock_ad(
    app_settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[tuple[AdClient, list[str]]]:
    """Mock-AD, das sich die Ziel-OU jeder Anlage merkt."""
    client = AdClient(
        app_settings.model_copy(
            update={"ad_use_mock": True, "ad_users_search_base": "DC=schule,DC=local"}
        )
    )
    seen: list[str] = []
    original = client.create_user

    async def spy(**kwargs: Any) -> str:
        seen.append(kwargs["ou_dn"])
        return await original(**kwargs)

    monkeypatch.setattr(client, "create_user", spy)
    yield client, seen
    await client.aclose()


@pytest_asyncio.fixture
async def _ous(db_session: AsyncSession, school_a: int) -> None:
    school = await db_session.get(School, school_a)
    assert school is not None
    school.ad_ou_teachers = "OU=Lehrer,OU=A,DC=schule,DC=local"
    await db_session.commit()


async def _template(as_admin: AsyncClient, school_id: int, **extra: Any) -> dict[str, Any]:
    r = await as_admin.post(
        "/admin/group-templates",
        json={"name": "Gäste", "ad_groups": [], "school_ids": [school_id], **extra},
    )
    assert r.status_code == 201, r.text
    return dict(r.json())


async def _create(as_admin: AsyncClient, app: FastAPI, ad: AdClient, body: dict[str, Any]) -> Any:
    app.dependency_overrides[get_ad_client] = lambda: ad
    try:
        return await as_admin.post("/ad/users", json=body)
    finally:
        app.dependency_overrides.pop(get_ad_client, None)


def _user(upn: str, school_id: int, template_id: int) -> dict[str, Any]:
    return {
        "given_name": "Gast",
        "surname": upn.split("@")[0],
        "sam_account_name": upn.split("@")[0][:20],
        "user_principal_name": upn,
        "ou_key": "teacher",
        "school_id": school_id,
        "group_template_id": template_id,
    }


@pytest.mark.asyncio
async def test_free_zielgruppe_creates_in_its_own_ou(
    as_admin: AsyncClient,
    app: FastAPI,
    school_a: int,
    mock_ad: tuple[AdClient, list[str]],
    _ous: None,
) -> None:
    ad, seen = mock_ad
    tpl = await _template(
        as_admin, school_a, kind="custom", ad_ou=" OU=Gaeste , OU=A,DC=schule,DC=local"
    )
    # Leerzeichen um die Kommas werden entfernt.
    assert tpl["ad_ou"] == GUEST_OU
    r = await _create(as_admin, app, ad, _user("gast1@schule.ch", school_a, tpl["id"]))
    assert r.status_code == 201, r.text
    assert seen == [GUEST_OU]


@pytest.mark.asyncio
async def test_without_ou_the_school_ou_applies(
    as_admin: AsyncClient,
    app: FastAPI,
    school_a: int,
    mock_ad: tuple[AdClient, list[str]],
    _ous: None,
) -> None:
    ad, seen = mock_ad
    tpl = await _template(as_admin, school_a, kind="custom")
    assert tpl["ad_ou"] is None
    r = await _create(as_admin, app, ad, _user("gast2@schule.ch", school_a, tpl["id"]))
    assert r.status_code == 201, r.text
    assert seen == ["OU=Lehrer,OU=A,DC=schule,DC=local"]


@pytest.mark.asyncio
async def test_ou_outside_the_school_is_refused(
    as_admin: AsyncClient,
    app: FastAPI,
    school_a: int,
    mock_ad: tuple[AdClient, list[str]],
    _ous: None,
) -> None:
    ad, seen = mock_ad
    tpl = await _template(as_admin, school_a, kind="custom", ad_ou="OU=Gaeste,DC=schule,DC=local")
    r = await _create(as_admin, app, ad, _user("gast3@schule.ch", school_a, tpl["id"]))
    assert r.status_code == 409
    assert r.json()["detail"] == "ou_outside_school"
    assert seen == []


@pytest.mark.asyncio
async def test_fixed_kind_drops_the_ou_and_bad_dn_is_422(
    as_admin: AsyncClient, school_a: int
) -> None:
    tpl = await _template(as_admin, school_a, kind="teacher", ad_ou=GUEST_OU)
    assert tpl["ad_ou"] is None
    bad = await as_admin.post(
        "/admin/group-templates",
        json={"name": "Kaputt", "kind": "custom", "ad_ou": "Gaeste"},
    )
    assert bad.status_code == 422

    free = await _template(as_admin, school_a, kind="custom", ad_ou=GUEST_OU)
    # "" entfernt die Ziel-OU wieder; None (weggelassen) lässt sie stehen.
    kept = await as_admin.patch(f"/admin/group-templates/{free['id']}", json={"name": "Gäste 2"})
    assert kept.json()["ad_ou"] == GUEST_OU
    cleared = await as_admin.patch(f"/admin/group-templates/{free['id']}", json={"ad_ou": ""})
    assert cleared.json()["ad_ou"] is None


@pytest.mark.asyncio
async def test_import_with_named_free_zielgruppe_uses_its_ou(
    as_admin: AsyncClient,
    app: FastAPI,
    school_a: int,
    mock_ad: tuple[AdClient, list[str]],
    _ous: None,
) -> None:
    ad, seen = mock_ad
    await _template(as_admin, school_a, kind="custom", ad_ou=GUEST_OU)
    outside = await as_admin.post(
        "/admin/group-templates",
        json={
            "name": "Draussen",
            "kind": "custom",
            "ad_ou": "OU=Draussen,DC=schule,DC=local",
            "school_ids": [school_a],
        },
    )
    assert outside.status_code == 201, outside.text
    csv = (
        "given_name,surname,display_name,upn,sam_account_name,force_change,"
        "cannot_change_password,password_never_expires,zielgruppe\n"
        "Gina,Gast,,gina.gast@schule.ch,,,,,Gäste\n"
        "Otto,Out,,otto.out@schule.ch,,,,,Draussen\n"
    )
    r = await as_admin.post(
        f"/imports?kind=teachers&school_id={school_a}",
        files={"file": ("t.csv", csv, "text/csv")},
    )
    assert r.status_code == 201, r.text
    detail = (await as_admin.get(f"/imports/{r.json()['id']}")).json()
    by_upn = {row["raw_data"]["upn"]: row for row in detail["rows"]}
    assert by_upn["gina.gast@schule.ch"]["action"] == "create"
    assert by_upn["otto.out@schule.ch"]["action"] == "error"
    assert "outside this school" in by_upn["otto.out@schule.ch"]["errors"][0]

    app.dependency_overrides[imports_ad_client] = lambda: ad
    try:
        applied = await as_admin.post(f"/imports/{r.json()['id']}/apply")
    finally:
        app.dependency_overrides.pop(imports_ad_client, None)
    assert applied.status_code == 200, applied.text
    assert seen == [GUEST_OU]


OTHER_OU = "OU=Sonstige,DC=schule,DC=local"


def _plain(upn: str, **extra: Any) -> dict[str, Any]:
    local = upn.split("@")[0]
    return {
        "given_name": "Ohne",
        "surname": local,
        "sam_account_name": local[:20],
        "user_principal_name": upn,
        "ou_key": "student_zyklus1",
        **extra,
    }


@pytest.mark.asyncio
async def test_explicit_ou_at_creation(
    as_admin: AsyncClient,
    app: FastAPI,
    db_session: AsyncSession,
    school_a: int,
    mock_ad: tuple[AdClient, list[str]],
    _ous: None,
) -> None:
    ad, seen = mock_ad
    # Ohne Standort, ohne Zielgruppe: die angegebene OU — auch für Schüler:innen.
    r = await _create(as_admin, app, ad, _plain("ohne1@schule.ch", ad_ou=OTHER_OU))
    assert r.status_code == 201, r.text
    # Ohne Standort und ohne OU: abgelehnt, nichts im AD.
    r = await _create(as_admin, app, ad, _plain("ohne2@schule.ch"))
    assert r.status_code == 422
    assert r.json()["detail"] == "ou_required_without_school"
    # Die angegebene OU gewinnt vor der Ziel-OU der Zielgruppe.
    free = await _template(as_admin, school_a, kind="custom", ad_ou=GUEST_OU)
    r = await _create(
        as_admin,
        app,
        ad,
        _plain(
            "mit1@schule.ch",
            school_id=school_a,
            group_template_id=free["id"],
            ad_ou="OU=Extern,OU=A,DC=schule,DC=local",
        ),
    )
    assert r.status_code == 201, r.text
    # Mit Standort muss sie in ihm liegen.
    r = await _create(
        as_admin, app, ad, _plain("mit2@schule.ch", school_id=school_a, ad_ou=OTHER_OU)
    )
    assert r.status_code == 409
    assert r.json()["detail"] == "ou_outside_school"
    # Bei fester Kontoart legt der Standort die OU fest.
    fixed = await _template(as_admin, school_a, kind="teacher")
    r = await _create(
        as_admin,
        app,
        ad,
        _plain("mit3@schule.ch", school_id=school_a, group_template_id=fixed["id"], ad_ou=GUEST_OU),
    )
    assert r.status_code == 422
    assert r.json()["detail"] == "ou_not_allowed_for_kind"
    assert seen == [OTHER_OU, "OU=Extern,OU=A,DC=schule,DC=local"]


@pytest.mark.asyncio
async def test_without_school_the_zielgruppe_needs_an_ou_also_with_fixed_kind(
    as_admin: AsyncClient,
    app: FastAPI,
    school_a: int,
    mock_ad: tuple[AdClient, list[str]],
    _ous: None,
) -> None:
    ad, seen = mock_ad
    # Ohne Standort: Pflicht, auch bei fester Kontoart.
    r = await as_admin.post("/admin/group-templates", json={"name": "Global LP", "kind": "teacher"})
    assert r.status_code == 422
    assert r.json()["detail"] == "ad_ou_required_without_school"
    glob = await as_admin.post(
        "/admin/group-templates",
        json={"name": "Global LP", "kind": "teacher", "ad_ou": OTHER_OU},
    )
    assert glob.status_code == 201, glob.text
    assert glob.json()["ad_ou"] == OTHER_OU
    # Standort wieder abwählen ohne OU geht nicht; mit Standort fällt sie bei
    # fester Kontoart weg (dort gilt die OU des Standorts).
    bound = await _template(as_admin, school_a, kind="teacher")
    r = await as_admin.patch(f"/admin/group-templates/{bound['id']}", json={"school_ids": []})
    assert r.status_code == 422

    # Anlage ohne Standort: die OU der globalen Zielgruppe.
    r = await _create(
        as_admin, app, ad, _plain("global1@schule.ch", group_template_id=glob.json()["id"])
    )
    assert r.status_code == 201, r.text
    # Mit Standort: dessen Lehrpersonen-OU, nicht die der Zielgruppe.
    r = await _create(
        as_admin,
        app,
        ad,
        _plain("global2@schule.ch", school_id=school_a, group_template_id=glob.json()["id"]),
    )
    assert r.status_code == 201, r.text
    assert seen == [OTHER_OU, "OU=Lehrer,OU=A,DC=schule,DC=local"]
