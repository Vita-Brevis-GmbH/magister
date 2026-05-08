"""Local-admin login + lifecycle service.

The local admin is a single break-glass account used for:
- Day-1 deployments before OIDC is configured
- Recovery when OIDC/Entra is unavailable

It maps onto Magister's existing auth model via three rows that are seeded
together on first run:
- ``local_admins`` (id=1) — username + argon2id hash + lockout state
- ``ad_user_cache`` (sentinel guid) — minimal stub so the existing UPN lookup
  in ``current_user.get_optional_user`` keeps working unchanged
- ``role_assignments`` (sentinel guid, role=admin, school_id=NULL) — the
  ``admin`` role grant
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import timedelta
from enum import Enum

from sqlalchemy.ext.asyncio import AsyncSession

from magister_api.auth.passwords import hash_password, needs_rehash, verify_password
from magister_api.config import Settings
from magister_api.models.auth import AdUserCache
from magister_api.models.base import utcnow
from magister_api.models.local_admin import LocalAdmin
from magister_api.repositories.auth import AdUserCacheRepository, RoleAssignmentRepository
from magister_api.repositories.local_admin import LocalAdminRepository

logger = logging.getLogger(__name__)

#: Stable sentinel ad_object_guid for the local-admin's auth rows. 36 chars,
#: matches the shape of a UUID without ever colliding with a real Entra oid
#: (zeros are reserved per RFC 4122 nil-UUID semantics).
LOCAL_ADMIN_GUID = "00000000-0000-0000-0000-000000000001"

#: Upper-bound on consecutive failures before the account is locked.
MAX_FAILED_ATTEMPTS = 5

#: Lockout window after the cap is hit.
LOCKOUT_DURATION = timedelta(minutes=15)


class LoginRefusal(Enum):
    UNKNOWN_USER = "invalid_credentials"
    WRONG_PASSWORD = "invalid_credentials"  # noqa: S105 — enum name, not a credential
    DISABLED = "local_login_disabled"
    LOCKED = "account_locked"


@dataclass(frozen=True)
class LoginOk:
    admin: LocalAdmin


@dataclass(frozen=True)
class LoginFailed:
    reason: LoginRefusal


LoginResult = LoginOk | LoginFailed


class LocalAdminService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # ---------- auth ----------

    async def authenticate(self, username: str, password: str) -> LoginResult:
        """Verify *password* for *username*, applying lockout policy.

        Side-effects:
        - on success: resets ``failed_login_count``, clears ``locked_until``,
          sets ``last_login_at``, and rehashes if argon2 parameters changed.
        - on wrong password: increments ``failed_login_count``; trips the
          15-min lock when the threshold is reached.
        Caller is responsible for the audit event (it's per-route).
        """
        repo = LocalAdminRepository(self.session)
        admin = await repo.get_by_username(username)
        if admin is None:
            # Time-equalising verify against a throwaway hash. Avoids the
            # username-enumeration side-channel where wrong-username returns
            # in 1ms while wrong-password takes 50-100ms (argon2 cost).
            verify_password(password, _BURN_HASH)
            return LoginFailed(LoginRefusal.UNKNOWN_USER)

        if not admin.enabled:
            return LoginFailed(LoginRefusal.DISABLED)

        now = utcnow()
        if admin.locked_until is not None and admin.locked_until > now:
            return LoginFailed(LoginRefusal.LOCKED)
        if admin.locked_until is not None and admin.locked_until <= now:
            # Lockout expired — clear so the counter starts fresh.
            admin.locked_until = None
            admin.failed_login_count = 0

        if not verify_password(password, admin.password_hash):
            admin.failed_login_count += 1
            if admin.failed_login_count >= MAX_FAILED_ATTEMPTS:
                admin.locked_until = now + LOCKOUT_DURATION
            await self.session.flush()
            return LoginFailed(LoginRefusal.WRONG_PASSWORD)

        admin.failed_login_count = 0
        admin.locked_until = None
        admin.last_login_at = now
        if needs_rehash(admin.password_hash):
            admin.password_hash = hash_password(password)
        await self.session.flush()
        return LoginOk(admin=admin)

    # ---------- mutations ----------

    async def change_password(self, *, current_password: str, new_password: str) -> bool:
        admin = await LocalAdminRepository(self.session).get()
        if admin is None:
            return False
        if not verify_password(current_password, admin.password_hash):
            return False
        admin.password_hash = hash_password(new_password)
        admin.password_changed_at = utcnow()
        admin.failed_login_count = 0
        admin.locked_until = None
        await self.session.flush()
        return True

    async def set_enabled(self, enabled: bool) -> LocalAdmin | None:
        admin = await LocalAdminRepository(self.session).get()
        if admin is None:
            return None
        admin.enabled = enabled
        if enabled:
            # Re-enabling clears any pending lock so ops aren't surprised.
            admin.locked_until = None
            admin.failed_login_count = 0
        await self.session.flush()
        return admin

    # ---------- bootstrap ----------

    async def seed_from_env_if_empty(self, settings: Settings) -> bool:
        """Idempotent seed from ``MAGISTER_LOCAL_ADMIN_*`` env on first boot.

        Returns True iff a row was created. Refuses to seed plaintext: only a
        pre-computed argon2id hash is accepted via
        ``MAGISTER_LOCAL_ADMIN_PASSWORD_HASH``. Use ``magister-cli
        hash-password`` to produce one.
        """
        repo = LocalAdminRepository(self.session)
        if await repo.get() is not None:
            return False

        username = settings.local_admin_username
        password_hash = (
            settings.local_admin_password_hash.get_secret_value()
            if settings.local_admin_password_hash is not None
            else ""
        )
        if not username or not password_hash:
            logger.warning(
                "local_admins table is empty and "
                "MAGISTER_LOCAL_ADMIN_USERNAME/_PASSWORD_HASH are not set — "
                "no local admin will exist; OIDC will be the only login path"
            )
            return False
        if not password_hash.startswith("$argon2"):
            logger.error(
                "MAGISTER_LOCAL_ADMIN_PASSWORD_HASH does not look like an "
                "argon2id hash; refusing to seed the local admin. Use "
                "`magister-cli hash-password` to produce a valid hash."
            )
            return False

        now = utcnow()
        admin = LocalAdmin(
            id=1,
            username=username,
            password_hash=password_hash,
            enabled=True,
            failed_login_count=0,
            locked_until=None,
            last_login_at=None,
            password_changed_at=now,
            created_at=now,
        )
        self.session.add(admin)

        # Seed the AdUserCache + RoleAssignment rows so the existing
        # current_user.get_optional_user / RBAC pipeline keeps working
        # unchanged for local sessions.
        cache_repo = AdUserCacheRepository(self.session)
        existing_cache = await self.session.get(AdUserCache, LOCAL_ADMIN_GUID)
        if existing_cache is None:
            await cache_repo.upsert_admin(
                ad_object_guid=LOCAL_ADMIN_GUID,
                upn=f"{username}@magister.local",
                ms_ds_consistency_guid=None,
            )
        roles_repo = RoleAssignmentRepository(self.session)
        await roles_repo.grant(
            ad_object_guid=LOCAL_ADMIN_GUID,
            role="admin",
            school_id=None,
            granted_by="bootstrap",
        )
        await self.session.flush()
        await self.session.commit()
        logger.warning(
            "Local admin seeded from MAGISTER_LOCAL_ADMIN_PASSWORD_HASH — "
            "the env var can now be removed; the password is in the DB."
        )
        return True


# Pre-computed throwaway hash used for timing-equalisation in
# `authenticate()`. It exists solely so verify_password(_, _BURN_HASH)
# spends roughly the same wall time as a real verify, defending against
# username-enumeration timing attacks.
_BURN_HASH = hash_password("not-a-real-password-just-burning-cpu-cycles")


__all__ = [
    "LOCAL_ADMIN_GUID",
    "LocalAdminService",
    "LoginFailed",
    "LoginOk",
    "LoginRefusal",
    "LoginResult",
]
