"""User lifecycle service: enable/disable AD account + cache + audit (M2 US-6).

Orchestrates the three writes that must move together when a Schulleitung
off-boards (or re-activates) a user:

1. LDAP MODIFY of ``userAccountControl`` (flip ``ACCOUNTDISABLE`` bit) — fresh
   read-modify-write via :meth:`AdClient.set_account_enabled` so other UAC
   bits are preserved.
2. ``ad_user_cache.enabled`` mirror update in the same DB transaction.
3. Audit event ``user_enabled`` / ``user_disabled`` (success) or
   ``user_status_change_failed`` (AD MODIFY threw).

Idempotent: if AD reports the account is already in the target state, no
MODIFY, no audit, and the cache is aligned to AD truth.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from magister_api.ad.client import AdClient
from magister_api.ad.errors import AdUnavailableError
from magister_api.audit.service import AuditService
from magister_api.auth.current_user import AuthenticatedUser
from magister_api.config import Settings
from magister_api.models.auth import AdUserCache
from magister_api.services.user_attrs import UserNotInAdError


class CannotDisableSelfError(Exception):
    """Caller tried to disable their own account."""


class UserLifecycleService:
    def __init__(self, session: AsyncSession, settings: Settings, ad: AdClient) -> None:
        self.session = session
        self.settings = settings
        self.ad = ad
        self.audit = AuditService(session, settings)

    async def set_enabled(
        self,
        target: AdUserCache,
        *,
        enabled: bool,
        reason: str | None,
        actor: AuthenticatedUser,
        ip: str | None,
        request_id: str,
    ) -> AdUserCache:
        if not enabled and target.ad_object_guid == actor.ad_object_guid:
            raise CannotDisableSelfError()

        user_dn = await self.ad.find_user_dn(target.ad_object_guid)
        if user_dn is None:
            raise UserNotInAdError()

        try:
            previous, new = await self.ad.set_account_enabled(user_dn=user_dn, enabled=enabled)
        except AdUnavailableError as exc:
            await self.audit.emit(
                action="user_status_change_failed",
                target_kind="user",
                target_id=target.ad_object_guid,
                actor_upn=actor.upn,
                actor_object_guid=actor.ad_object_guid,
                school_id=target.school_id,
                ip=ip,
                request_id=request_id,
                payload={"requested_enabled": enabled, "reason": str(exc)},
            )
            raise

        # Mirror AD truth into the cache regardless of whether a MODIFY ran —
        # an idempotent call still aligns a stale cache row.
        target.enabled = new

        if previous == new:
            return target

        await self.audit.emit(
            action="user_enabled" if new else "user_disabled",
            target_kind="user",
            target_id=target.ad_object_guid,
            actor_upn=actor.upn,
            actor_object_guid=actor.ad_object_guid,
            school_id=target.school_id,
            ip=ip,
            request_id=request_id,
            payload={
                "previous_enabled": previous,
                "new_enabled": new,
                "reason": reason or "",
            },
        )
        return target
