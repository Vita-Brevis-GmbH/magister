"""Admin-only ``/admin/app-settings`` endpoints + cache invalidation."""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from magister_api.config import Settings
from magister_api.models.app_settings import AppSettings

pytestmark = pytest.mark.postgres


class TestRequiresAdmin:
    async def test_get_rejects_anonymous(self, client: AsyncClient) -> None:
        resp = await client.get("/admin/app-settings")
        assert resp.status_code == 401

    async def test_put_rejects_schulleitung(self, as_schulleitung_a: AsyncClient) -> None:
        resp = await as_schulleitung_a.put(
            "/admin/app-settings",
            json={"oidc_issuer": "https://x.test/v2.0"},
        )
        assert resp.status_code == 403


class TestGet:
    async def test_initial_state_has_no_secrets_set(self, as_admin: AsyncClient) -> None:
        resp = await as_admin.get("/admin/app-settings")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["oidc_client_secret_set"] is False
        assert body["ad_bind_password_set"] is False
        assert "oidc_client_secret" not in body
        assert "ad_bind_password" not in body
        assert body["version"] == 1


class TestPut:
    async def test_happy_path_persists_and_redacts_secrets(
        self, as_admin: AsyncClient, db_session: AsyncSession
    ) -> None:
        resp = await as_admin.put(
            "/admin/app-settings",
            json={
                "oidc_issuer": "https://entra.example.test/v2.0",
                "oidc_client_id": "client-x",
                "oidc_client_secret": "fresh-secret-value",
                "ad_dcs": ["dc1.test"],
                "ad_bind_password": "fresh-bind-pw",
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["oidc_issuer"] == "https://entra.example.test/v2.0"
        assert body["oidc_client_id"] == "client-x"
        assert body["oidc_client_secret_set"] is True
        assert body["ad_bind_password_set"] is True
        assert "fresh-secret-value" not in resp.text
        assert "fresh-bind-pw" not in resp.text
        assert body["version"] >= 2

    async def test_omitting_secret_leaves_stored_value(
        self, as_admin: AsyncClient, db_session: AsyncSession
    ) -> None:
        # Seed a secret first
        await as_admin.put(
            "/admin/app-settings",
            json={"oidc_client_secret": "initial-secret-value"},
        )
        before = (
            await db_session.execute(
                select(AppSettings.oidc_client_secret_enc).where(AppSettings.id == 1)
            )
        ).scalar_one()
        # Update an unrelated field
        await as_admin.put(
            "/admin/app-settings",
            json={"oidc_issuer": "https://other.test/v2.0"},
        )
        after = (
            await db_session.execute(
                select(AppSettings.oidc_client_secret_enc).where(AppSettings.id == 1)
            )
        ).scalar_one()
        assert before == after  # encrypted bytea unchanged


class TestCapabilitiesReflectsDb:
    async def test_oidc_enabled_flips_with_settings(
        self,
        client: AsyncClient,
        as_admin: AsyncClient,
        app_settings: Settings,
    ) -> None:
        # The conftest's app_settings fixture pre-sets oidc_issuer +
        # oidc_client_id in env. After the fresh `app_settings` row has
        # NULL OIDC fields, the env is the only source — but our overlay
        # uses env values when DB values are empty, so capabilities still
        # reports oidc_enabled=True.
        before = await client.get("/auth/capabilities")
        assert before.json()["oidc_enabled"] is True

        # Now write empty-but-configured DB row that still has issuer set.
        await as_admin.put(
            "/admin/app-settings",
            json={
                "oidc_issuer": "https://from-db.test/v2.0",
                "oidc_client_id": "from-db-client",
            },
        )
        after = await client.get("/auth/capabilities")
        body = after.json()
        assert body["oidc_enabled"] is True
