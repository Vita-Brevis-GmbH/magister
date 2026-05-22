"""AppSettingsService — encryption, version bump, redaction, seed-from-env."""

from __future__ import annotations

import pytest
from pydantic import SecretStr
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from magister_api.config import Settings
from magister_api.models.app_settings import AppSettings
from magister_api.schemas.app_settings import AppSettingsUpdate
from magister_api.services.app_settings import AppSettingsService

pytestmark = pytest.mark.postgres


def _settings(**overrides: object) -> Settings:
    base: dict[str, object] = {
        "environment": "test",
        "database_url": "postgresql+asyncpg://x/y",
        "audit_key": SecretStr("integration-audit-key"),
        "session_secret": SecretStr("x"),
        "csrf_secret": SecretStr("x"),
    }
    base |= overrides
    return Settings(**base)  # type: ignore[arg-type]


class TestRedactedAndEffective:
    async def test_get_redacted_does_not_carry_plaintext_secrets(
        self, db_session: AsyncSession
    ) -> None:
        svc = AppSettingsService(db_session, _settings())
        await svc.update(
            AppSettingsUpdate(
                oidc_issuer="https://login.example.test/v2.0",
                oidc_client_id="client-abc",
                oidc_client_secret="super-secret-value-123",
                ad_bind_password="bind-pw-78901",
            ),
            actor_upn="admin@example.ch",
            actor_object_guid=None,
            ip=None,
            request_id="r1",
        )
        out = await svc.get_redacted_for_api()
        assert out.oidc_issuer == "https://login.example.test/v2.0"
        assert out.oidc_client_id == "client-abc"
        assert out.oidc_client_secret_set is True
        assert out.ad_bind_password_set is True
        # Round-trip via dict — no key in the JSON-serialisable view starts
        # with "secret" or contains the plaintext.
        dumped = out.model_dump()
        assert "oidc_client_secret" not in dumped
        assert "ad_bind_password" not in dumped
        for v in dumped.values():
            assert "super-secret-value-123" not in str(v)
            assert "bind-pw-78901" not in str(v)

    async def test_get_effective_decrypts_secrets(self, db_session: AsyncSession) -> None:
        svc = AppSettingsService(db_session, _settings())
        await svc.update(
            AppSettingsUpdate(
                oidc_issuer="https://login.example.test/v2.0",
                oidc_client_id="client-abc",
                oidc_client_secret="round-trip-secret",
                ad_bind_password="round-trip-bind-pw",
            ),
            actor_upn="admin@example.ch",
            actor_object_guid=None,
            ip=None,
            request_id="r2",
        )
        eff = await svc.get_effective()
        assert eff.oidc_client_secret == "round-trip-secret"
        assert eff.ad_bind_password == "round-trip-bind-pw"


class TestVersionBumping:
    async def test_update_bumps_version(self, db_session: AsyncSession) -> None:
        svc = AppSettingsService(db_session, _settings())
        v0 = await svc.get_version()
        await svc.update(
            AppSettingsUpdate(oidc_issuer="https://x.test/v2.0"),
            actor_upn="admin@example.ch",
            actor_object_guid=None,
            ip=None,
            request_id="r",
        )
        v1 = await svc.get_version()
        assert v1 == v0 + 1


class TestPartialUpdates:
    async def test_omitting_secret_leaves_stored_value(self, db_session: AsyncSession) -> None:
        svc = AppSettingsService(db_session, _settings())
        await svc.update(
            AppSettingsUpdate(oidc_client_secret="initial-secret"),
            actor_upn="admin@example.ch",
            actor_object_guid=None,
            ip=None,
            request_id="r1",
        )
        # Capture the raw encrypted bytea so we can confirm it doesn't
        # change on the next update.
        before = (
            await db_session.execute(
                select(AppSettings.oidc_client_secret_enc).where(AppSettings.id == 1)
            )
        ).scalar_one()

        # Update an unrelated field without sending the secret again.
        await svc.update(
            AppSettingsUpdate(oidc_issuer="https://other.test/v2.0"),
            actor_upn="admin@example.ch",
            actor_object_guid=None,
            ip=None,
            request_id="r2",
        )
        after = (
            await db_session.execute(
                select(AppSettings.oidc_client_secret_enc).where(AppSettings.id == 1)
            )
        ).scalar_one()
        assert before == after  # bytea unchanged

        # And the decrypted value is still the original.
        eff = await svc.get_effective()
        assert eff.oidc_client_secret == "initial-secret"

    async def test_empty_string_secret_does_not_overwrite(self, db_session: AsyncSession) -> None:
        svc = AppSettingsService(db_session, _settings())
        await svc.update(
            AppSettingsUpdate(oidc_client_secret="real-secret"),
            actor_upn="admin@example.ch",
            actor_object_guid=None,
            ip=None,
            request_id="r1",
        )
        await svc.update(
            AppSettingsUpdate(oidc_client_secret=""),
            actor_upn="admin@example.ch",
            actor_object_guid=None,
            ip=None,
            request_id="r2",
        )
        eff = await svc.get_effective()
        assert eff.oidc_client_secret == "real-secret"


class TestMailDomains:
    """`mail_domains` is the allowlist powering the user-edit form's UPN/mail dropdowns."""

    async def test_defaults_to_empty_list(self, db_session: AsyncSession) -> None:
        svc = AppSettingsService(db_session, _settings())
        out = await svc.get_redacted_for_api()
        assert out.mail_domains == []
        eff = await svc.get_effective()
        assert eff.mail_domains == []

    async def test_update_round_trips(self, db_session: AsyncSession) -> None:
        svc = AppSettingsService(db_session, _settings())
        await svc.update(
            AppSettingsUpdate(mail_domains=["schule.example.ch", "lehrer.example.ch"]),
            actor_upn="admin@example.ch",
            actor_object_guid=None,
            ip=None,
            request_id="r1",
        )
        out = await svc.get_redacted_for_api()
        assert out.mail_domains == ["schule.example.ch", "lehrer.example.ch"]
        eff = await svc.get_effective()
        assert eff.mail_domains == ["schule.example.ch", "lehrer.example.ch"]

    async def test_empty_list_clears(self, db_session: AsyncSession) -> None:
        svc = AppSettingsService(db_session, _settings())
        await svc.update(
            AppSettingsUpdate(mail_domains=["a.ch"]),
            actor_upn="admin@example.ch",
            actor_object_guid=None,
            ip=None,
            request_id="r1",
        )
        await svc.update(
            AppSettingsUpdate(mail_domains=[]),
            actor_upn="admin@example.ch",
            actor_object_guid=None,
            ip=None,
            request_id="r2",
        )
        out = await svc.get_redacted_for_api()
        assert out.mail_domains == []


class TestSingletonEnforcement:
    async def test_inserting_id_other_than_one_violates_check(
        self, db_session: AsyncSession
    ) -> None:
        from sqlalchemy import insert
        from sqlalchemy.exc import IntegrityError

        with pytest.raises(IntegrityError):
            await db_session.execute(insert(AppSettings).values(id=2, version=1))
            await db_session.flush()


class TestSeedFromEnv:
    async def test_seed_copies_env_into_empty_row(self, db_session: AsyncSession) -> None:
        env_settings = _settings(
            oidc_issuer="https://entra.example.test/v2.0",
            oidc_client_id="env-client-id",
            oidc_client_secret=SecretStr("env-secret-12345"),
            oidc_redirect_uri="https://magister.example.ch/api/auth/callback",
            ad_dcs=["dc1.example.local"],
            ad_bind_dn="cn=svc,dc=example,dc=local",
            ad_bind_password=SecretStr("env-bind-pw-67"),
            ad_users_search_base="OU=Users,DC=example,DC=local",
            bootstrap_admins=["admin@example.ch"],
        )
        svc = AppSettingsService(db_session, _settings())
        seeded = await svc.seed_from_env_if_empty(env_settings)
        assert seeded is True

        eff = await svc.get_effective()
        assert eff.oidc_issuer == "https://entra.example.test/v2.0"
        assert eff.oidc_client_id == "env-client-id"
        assert eff.oidc_client_secret == "env-secret-12345"
        assert eff.ad_dcs == ["dc1.example.local"]
        assert eff.ad_bind_password == "env-bind-pw-67"
        assert eff.bootstrap_admins == ["admin@example.ch"]

    async def test_seed_is_idempotent(self, db_session: AsyncSession) -> None:
        env_settings = _settings(
            oidc_issuer="https://e1.test/v2.0",
            oidc_client_id="id-1",
            oidc_client_secret=SecretStr("s1"),
        )
        svc = AppSettingsService(db_session, _settings())
        first = await svc.seed_from_env_if_empty(env_settings)
        second = await svc.seed_from_env_if_empty(
            _settings(
                oidc_issuer="https://e2.test/v2.0",  # different — must not overwrite
                oidc_client_id="id-2",
            )
        )
        assert first is True
        assert second is False

        # Still the first seed's values.
        eff = await svc.get_effective()
        assert eff.oidc_issuer == "https://e1.test/v2.0"
        assert eff.oidc_client_id == "id-1"


class TestAuditEmission:
    async def test_update_strips_secrets_from_audit_payload(self, db_session: AsyncSession) -> None:
        from magister_api.audit.service import AuditService
        from magister_api.models.audit import AuditEvent

        cfg = _settings()
        svc = AppSettingsService(db_session, cfg)
        await svc.update(
            AppSettingsUpdate(
                oidc_issuer="https://x.test/v2.0",
                oidc_client_secret="must-not-leak",
                ad_bind_password="also-must-not-leak",
            ),
            actor_upn="admin@example.ch",
            actor_object_guid=None,
            ip=None,
            request_id="audit-test",
        )
        rows = (
            (
                await db_session.execute(
                    select(AuditEvent.id).where(AuditEvent.action == "app_settings_updated")
                )
            )
            .scalars()
            .all()
        )
        assert len(rows) == 1
        rec = await AuditService(db_session, cfg).read(rows[0])
        assert rec is not None
        assert "must-not-leak" not in str(rec.payload)
        assert "also-must-not-leak" not in str(rec.payload)
        # Boolean change-flags survive (they're how the audit-log shows the
        # operator that the secret rotated, without leaking the value).
        assert rec.payload.get("rotated_oidc_credential") is True
        assert rec.payload.get("rotated_ad_credential") is True


# Silence the unused import warning when SecretStr appears only in helpers.
_ = func
