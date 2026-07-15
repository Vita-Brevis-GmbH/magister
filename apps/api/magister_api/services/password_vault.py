"""Per-user password vault: store/read the last set password, encrypted at rest.

Opt-in per user (``ad_user_cache.store_password``) and gated by the global
``app_settings.password_store_enabled`` switch. Encryption reuses the same
pgcrypto path and key (``app_secrets_key`` → ``MAGISTER_SECRETS_KEY`` or the
audit key) as the OIDC/AD-bind secrets, so the key stays server-side and a DB
dump alone cannot reveal passwords. Plaintext is never persisted.

Use case: Zyklus-2 student passwords that teachers know anyway and want kept as
a class password list.
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy import update as sqla_update
from sqlalchemy.ext.asyncio import AsyncSession

from magister_api.config import Settings
from magister_api.models.app_settings import AppSettings
from magister_api.models.auth import AdUserCache


class PasswordVaultService:
    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self.session = session
        self._settings = settings

    @property
    def _key(self) -> str:
        key = self._settings.app_secrets_key()
        if not key:
            raise RuntimeError(
                "neither MAGISTER_SECRETS_KEY nor MAGISTER_AUDIT_KEY is set — "
                "password-vault access refused"
            )
        return key

    async def enabled(self) -> bool:
        """True when the global password-store master switch is on."""
        stmt = select(AppSettings.password_store_enabled).where(AppSettings.id == 1)
        return bool((await self.session.execute(stmt)).scalar_one_or_none())

    async def store(self, ad_object_guid: str, plaintext: str) -> None:
        """Encrypt and persist ``plaintext`` for one user (pgcrypto)."""
        # scope-bypass: keyed by objectGUID; the caller already scope-checked
        # the target user before deciding to store its password.
        await self.session.execute(
            sqla_update(AdUserCache)
            .where(AdUserCache.ad_object_guid == ad_object_guid)
            .values(password_enc=func.pgp_sym_encrypt(plaintext, self._key))
        )

    async def get(self, ad_object_guid: str) -> str | None:
        """Decrypt and return the stored password, or ``None`` if unset."""
        stmt = select(func.pgp_sym_decrypt(AdUserCache.password_enc, self._key)).where(
            AdUserCache.ad_object_guid == ad_object_guid,
            AdUserCache.password_enc.is_not(None),
        )
        row = (await self.session.execute(stmt)).scalar_one_or_none()
        return str(row) if row is not None else None

    async def clear(self, ad_object_guid: str) -> None:
        """Drop the stored password (e.g. when the per-user flag is turned off)."""
        await self.session.execute(
            sqla_update(AdUserCache)
            .where(AdUserCache.ad_object_guid == ad_object_guid)
            .values(password_enc=None)
        )


__all__ = ["PasswordVaultService"]
