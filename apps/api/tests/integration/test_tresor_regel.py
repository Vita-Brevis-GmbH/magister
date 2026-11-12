"""Tresor nur bei festem Passwort; Anlage ohne Standort.

Festes Passwort heisst: keine erzwungene Änderung bei der ersten Anmeldung,
der Benutzer kann es nicht ändern, und es läuft nie ab. Nur dann legt
Magister es ab — überall: Zielgruppe, Konto-Einstellungen, Anlage, Reset.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from typing import Any

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from magister_api.ad.client import AdClient
from magister_api.config import Settings
from magister_api.models.app_settings import AppSettings
from magister_api.models.auth import AdUserCache
from magister_api.routers.admin_sync import get_ad_client
from magister_api.routers.users import get_ad_client as users_ad_client
from magister_api.services.password_vault import PasswordVaultService

pytestmark = pytest.mark.postgres

OTHER_OU = "OU=Sonstige,DC=schule,DC=local"
GUID = "00000000-0000-0000-0000-00000000c001"


@pytest_asyncio.fixture
async def mock_ad(app_settings: Settings) -> AsyncIterator[AdClient]:
    client = AdClient(
        app_settings.model_copy(
            update={"ad_use_mock": True, "ad_users_search_base": "DC=schule,DC=local"}
        )
    )
    client.mock_connection().strategy.add_entry(
        "CN=Kind,OU=A,DC=schule,DC=local",
        {
            "objectClass": ["user"],
            "objectGUID": uuid.UUID(GUID).bytes_le,
            "userPrincipalName": "kind@schule.ch",
            "userAccountControl": 0x200,
        },
    )
    yield client
    await client.aclose()


async def _vault_on(db_session: AsyncSession) -> None:
    await db_session.execute(
        update(AppSettings).where(AppSettings.id == 1).values(password_store_enabled=True)
    )
    await db_session.commit()


async def _template(as_admin: AsyncClient, **body: Any) -> dict[str, Any]:
    # Ohne Standort braucht eine Zielgruppe eine Ziel-OU.
    body.setdefault("ad_ou", OTHER_OU)
    r = await as_admin.post("/admin/group-templates", json={"name": "T", **body})
    assert r.status_code == 201, r.text
    return dict(r.json())


@pytest.mark.asyncio
async def test_zielgruppe_keeps_the_vault_only_for_a_fixed_password(
    as_admin: AsyncClient,
) -> None:
    fixed = {"force_change": False, "cannot_change_password": True, "password_never_expires": True}
    ok = await _template(as_admin, store_password=True, **fixed)
    assert ok["store_password"] is True
    for loosen in (
        {"force_change": True},
        {"cannot_change_password": False},
        {"password_never_expires": False},
    ):
        tpl = await _template(as_admin, store_password=True, **{**fixed, **loosen})
        assert tpl["store_password"] is False, loosen
    # Nimmt eine Änderung eine Bedingung weg, geht der Schalter mit aus.
    patched = await as_admin.patch(
        f"/admin/group-templates/{ok['id']}", json={"password_never_expires": False}
    )
    assert patched.json()["store_password"] is False


@pytest.mark.asyncio
async def test_account_vault_toggle_follows_the_rule(
    as_admin: AsyncClient,
    app: FastAPI,
    db_session: AsyncSession,
    app_settings: Settings,
    school_a: int,
    mock_ad: AdClient,
) -> None:
    await _vault_on(db_session)
    db_session.add(
        AdUserCache(
            ad_object_guid=GUID,
            school_id=school_a,
            upn="kind@schule.ch",
            kind="student",
            enabled=True,
            cannot_change_password=True,
            password_never_expires=False,
        )
    )
    await db_session.commit()
    app.dependency_overrides[users_ad_client] = lambda: mock_ad
    try:
        # Läuft ab → einschalten geht nicht.
        r = await as_admin.patch(f"/users/{GUID}", json={"store_password": True})
        assert r.status_code == 422
        assert r.json()["detail"] == "store_password_requires_fixed_password"
        # Zusammen mit "läuft nie ab" geht es.
        r = await as_admin.patch(
            f"/users/{GUID}", json={"store_password": True, "password_never_expires": True}
        )
        assert r.status_code == 200, r.text
        await PasswordVaultService(db_session, app_settings).store(GUID, "Sonne-Wald-42")
        await db_session.commit()
        # "Kann ändern" wieder erlauben → Tresor aus, Kopie weg.
        r = await as_admin.patch(f"/users/{GUID}", json={"cannot_change_password": False})
        assert r.status_code == 200, r.text
    finally:
        app.dependency_overrides.pop(users_ad_client, None)
    db_session.expire_all()
    row = await db_session.get(AdUserCache, GUID)
    assert row is not None
    assert row.store_password is False
    assert await PasswordVaultService(db_session, app_settings).get(GUID) is None


def _new_user(upn: str, **extra: Any) -> dict[str, Any]:
    local = upn.split("@")[0]
    return {
        "given_name": "Ohne",
        "surname": local,
        "sam_account_name": local[:20],
        "user_principal_name": upn,
        "ou_key": "teacher",
        **extra,
    }


async def _create(as_admin: AsyncClient, app: FastAPI, ad: AdClient, body: dict[str, Any]) -> Any:
    app.dependency_overrides[get_ad_client] = lambda: ad
    try:
        return await as_admin.post("/ad/users", json=body)
    finally:
        app.dependency_overrides.pop(get_ad_client, None)


@pytest.mark.asyncio
async def test_create_without_school_needs_a_global_zielgruppe_with_ou(
    as_admin: AsyncClient,
    app: FastAPI,
    db_session: AsyncSession,
    school_a: int,
    mock_ad: AdClient,
) -> None:
    other = await _template(as_admin, kind="custom", ad_ou=OTHER_OU)
    r = await _create(
        as_admin, app, mock_ad, _new_user("extern1@schule.ch", group_template_id=other["id"])
    )
    assert r.status_code == 201, r.text
    row = await db_session.get(AdUserCache, r.json()["ad_object_guid"])
    assert row is not None
    await db_session.refresh(row)
    assert row.school_id is None
    assert row.group_template_id == other["id"]

    # Ohne Standort und ohne Ziel-OU gibt es keinen Ablageort: eine solche
    # Zielgruppe lässt sich gar nicht speichern, eine Anlage ohne beides nicht.
    r = await as_admin.post("/admin/group-templates", json={"name": "Ohne alles", "kind": "custom"})
    assert r.status_code == 422
    assert r.json()["detail"] == "ad_ou_required_without_school"
    r = await _create(as_admin, app, mock_ad, _new_user("extern3@schule.ch"))
    assert r.status_code == 422
    assert r.json()["detail"] == "ou_required_without_school"

    # Eine an Standorte gebundene Zielgruppe gibt es ohne Standort nicht.
    bound = await _template(as_admin, kind="custom", ad_ou=OTHER_OU, school_ids=[school_a])
    r = await _create(
        as_admin, app, mock_ad, _new_user("extern4@schule.ch", group_template_id=bound["id"])
    )
    assert r.status_code == 409
    assert r.json()["detail"] == "group_template_not_for_school"
