"""Application configuration loaded from environment variables.

All Magister settings use the ``MAGISTER_`` prefix. Secrets are wrapped in
``SecretStr`` so they never accidentally land in logs or `repr()` output.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="MAGISTER_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    environment: str = Field(default="development")
    log_level: str = Field(default="INFO")

    database_url: str = Field(
        default="postgresql+asyncpg://magister:magister@localhost:5432/magister",
    )

    audit_key: SecretStr = Field(
        default=SecretStr(""),
        description="Symmetric key for pgcrypto pgp_sym_encrypt of audit_events.payload.",
    )

    oidc_issuer: str = Field(default="")
    oidc_client_id: str = Field(default="")
    oidc_client_secret: SecretStr = Field(default=SecretStr(""))
    oidc_redirect_uri: str = Field(default="http://localhost:8000/auth/callback")
    oidc_scopes: list[str] = Field(default_factory=lambda: ["openid", "profile", "email"])

    session_secret: SecretStr = Field(default=SecretStr(""))
    session_lifetime_minutes: int = Field(default=480)
    session_cookie_name: str = Field(default="magister_session")
    session_cookie_secure: bool = Field(default=True)

    csrf_secret: SecretStr = Field(default=SecretStr(""))
    csrf_cookie_name: str = Field(default="magister_csrf")
    csrf_header_name: str = Field(default="X-CSRF-Token")

    bootstrap_admins: list[str] = Field(default_factory=list)

    # Local-admin (break-glass) — only consulted on first boot when the
    # `local_admins` table is empty. Always pass a pre-computed argon2id
    # hash; plaintext is refused. See `magister-cli hash-password`.
    local_admin_username: str = Field(default="admin")
    local_admin_password_hash: SecretStr | None = Field(default=None)

    ad_dcs: list[str] = Field(default_factory=list)
    ad_bind_dn: str | None = None
    ad_bind_password: SecretStr | None = None
    ad_users_search_base: str | None = Field(
        default=None,
        description=(
            "LDAP search base for the periodic user sync (e.g. OU=Users,DC=schule,DC=local)."
        ),
    )
    ad_sync_interval_minutes: int = Field(default=15)
    ad_use_mock: bool = Field(
        default=False,
        description="When true the AD client uses ldap3's MOCK_SYNC strategy (tests).",
    )
    ad_ca_bundle_path: str | None = Field(
        default=None,
        description=(
            "Optional path to a PEM CA bundle that the LDAPS connection must "
            "verify the domain-controller cert against. When unset, ldap3 "
            "falls back to the OS trust store. Pin this to the Schulträger "
            "root CA for defence-in-depth against a compromised system CA."
        ),
    )
    ad_computers_search_base: str | None = Field(
        default=None,
        description=(
            "Optional LDAP base for the Computer-OU walk. Unset = device "
            "sync is skipped; device_name in ad_user_cache stays as-is."
        ),
    )

    rate_limit_auth: str = Field(default="10/minute")
    rate_limit_password_reset: str = Field(default="10/minute")

    @field_validator("bootstrap_admins", "ad_dcs", "oidc_scopes", mode="before")
    @classmethod
    def _split_csv(cls, v: Any) -> Any:
        if isinstance(v, str):
            return [s.strip() for s in v.split(",") if s.strip()]
        return v

    @field_validator("environment")
    @classmethod
    def _check_env(cls, v: str) -> str:
        allowed = {"development", "staging", "production", "test"}
        if v not in allowed:
            raise ValueError(f"environment must be one of {allowed}, got {v!r}")
        return v

    def require_runtime_secrets(self) -> None:
        """Raise if a runtime-required secret is empty.

        Only the cryptographic + DB env vars are mandatory now — OIDC + AD
        config moved into the ``app_settings`` table (M1.5b) and is editable
        from the GUI. The lifespan-seed copies any pre-existing
        ``MAGISTER_OIDC_*`` / ``MAGISTER_AD_*`` env into the DB on first
        boot, so existing deployments keep working without env after the
        upgrade.

        Intentionally NOT called at import time so unit tests can run with
        partial config; the FastAPI app factory calls this on startup.
        """
        missing: list[str] = []
        if not self.audit_key.get_secret_value():
            missing.append("MAGISTER_AUDIT_KEY")
        if not self.session_secret.get_secret_value():
            missing.append("MAGISTER_SESSION_SECRET")
        if not self.csrf_secret.get_secret_value():
            missing.append("MAGISTER_CSRF_SECRET")
        if missing:
            raise RuntimeError("Missing required runtime secrets: " + ", ".join(missing))


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


def reset_settings_cache() -> None:
    get_settings.cache_clear()
