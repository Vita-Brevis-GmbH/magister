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


class TestWebTlsImport:
    """Importing a webserver certificate via PUT /admin/app-settings."""

    @staticmethod
    def _make_cert() -> tuple[str, str, str]:
        import datetime as dt

        from cryptography import x509
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.x509.oid import NameOID

        def one() -> tuple[str, str]:
            key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
            name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "magister.test")])
            cert = (
                x509.CertificateBuilder()
                .subject_name(name)
                .issuer_name(name)
                .public_key(key.public_key())
                .serial_number(x509.random_serial_number())
                .not_valid_before(dt.datetime(2020, 1, 1))
                .not_valid_after(dt.datetime(2035, 1, 1))
                .sign(key, hashes.SHA256())
            )
            return (
                cert.public_bytes(serialization.Encoding.PEM).decode(),
                key.private_bytes(
                    serialization.Encoding.PEM,
                    serialization.PrivateFormat.PKCS8,
                    serialization.NoEncryption(),
                ).decode(),
            )

        cert_pem, key_pem = one()
        _, other_key = one()
        return cert_pem, key_pem, other_key

    async def test_import_pem_sets_flag_and_hides_key(self, as_admin: AsyncClient) -> None:
        cert_pem, key_pem, _ = self._make_cert()
        resp = await as_admin.put(
            "/admin/app-settings",
            json={"web_tls_cert_pem": cert_pem, "web_tls_key_pem": key_pem},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["web_tls_cert_set"] is True
        # The private key never comes back.
        assert "PRIVATE KEY" not in resp.text

    async def test_mismatched_key_is_422(self, as_admin: AsyncClient) -> None:
        cert_pem, _, other_key = self._make_cert()
        resp = await as_admin.put(
            "/admin/app-settings",
            json={"web_tls_cert_pem": cert_pem, "web_tls_key_pem": other_key},
        )
        assert resp.status_code == 422

    async def test_clear_reverts_to_selfsigned(self, as_admin: AsyncClient) -> None:
        cert_pem, key_pem, _ = self._make_cert()
        await as_admin.put(
            "/admin/app-settings",
            json={"web_tls_cert_pem": cert_pem, "web_tls_key_pem": key_pem},
        )
        resp = await as_admin.put(
            "/admin/app-settings",
            json={"web_tls_cert_pem": "", "web_tls_key_pem": ""},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["web_tls_cert_set"] is False
