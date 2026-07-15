"""``/admin/user-settings`` (manage tier) + ``/admin/ad-groups`` catalog."""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from magister_api.models.ad_group import AdGroupCache

pytestmark = pytest.mark.postgres


class TestRbac:
    async def test_get_rejects_anonymous(self, client: AsyncClient) -> None:
        resp = await client.get("/admin/user-settings")
        assert resp.status_code == 401

    async def test_schulleitung_may_read(self, as_schulleitung_a: AsyncClient) -> None:
        # Group assignment is a manage-tier surface — Schulleitung is allowed
        # (unlike the admin-only /admin/app-settings).
        resp = await as_schulleitung_a.get("/admin/user-settings")
        assert resp.status_code == 200, resp.text

    async def test_smi_may_update(self, as_smi_a: AsyncClient) -> None:
        resp = await as_smi_a.put(
            "/admin/user-settings",
            json={"ad_groups_teacher": ["CN=Lehrer,OU=Groups,DC=x"]},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["ad_groups_teacher"] == ["CN=Lehrer,OU=Groups,DC=x"]


class TestUpdate:
    async def test_round_trips_ou_and_groups(self, as_admin: AsyncClient) -> None:
        resp = await as_admin.put(
            "/admin/user-settings",
            json={
                "ad_ou_teachers": "OU=Lehrer,DC=x",
                "ad_groups_search_base": "OU=Groups,DC=x",
                "ad_groups_student_zyklus3": ["CN=SekI,OU=Groups,DC=x"],
                "password_store_enabled": True,
            },
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["ad_ou_teachers"] == "OU=Lehrer,DC=x"
        assert body["ad_groups_search_base"] == "OU=Groups,DC=x"
        assert body["ad_groups_student_zyklus3"] == ["CN=SekI,OU=Groups,DC=x"]
        assert body["password_store_enabled"] is True

    async def test_does_not_touch_oidc_secret_surface(self, as_admin: AsyncClient) -> None:
        # The user-config PUT must never accept OIDC/AD secret fields.
        resp = await as_admin.put(
            "/admin/user-settings",
            json={"oidc_issuer": "https://evil.test", "ad_groups_teacher": ["CN=x,DC=y"]},
        )
        assert resp.status_code == 200
        # Extra keys are ignored by the restricted schema.
        settings = await as_admin.get("/admin/app-settings")
        assert settings.json()["oidc_issuer"] != "https://evil.test"


class TestAdGroupsCatalog:
    async def test_lists_synced_groups(
        self, as_admin: AsyncClient, db_session: AsyncSession
    ) -> None:
        db_session.add(
            AdGroupCache(
                ad_object_guid="11111111-1111-1111-1111-111111111111",
                distinguished_name="CN=Klasse3a,OU=Groups,DC=x",
                cn="Klasse3a",
                sam_account_name="Klasse3a",
                description="Schülergruppe 3a",
            )
        )
        await db_session.commit()
        resp = await as_admin.get("/admin/ad-groups")
        assert resp.status_code == 200, resp.text
        cns = {g["cn"] for g in resp.json()}
        assert "Klasse3a" in cns

    async def test_rejects_anonymous(self, client: AsyncClient) -> None:
        resp = await client.get("/admin/ad-groups")
        assert resp.status_code == 401
