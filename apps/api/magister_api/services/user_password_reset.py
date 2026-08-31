"""Generic user password-reset orchestration (company / non-class users).

Parallel to :mod:`student_password_reset` and :mod:`teacher_password_reset` for
users that are neither — company ``Benutzer`` and any future kind. Same
allowlist / no-plaintext-in-audit guarantees; the deltas are the audit action
names (``user_password_reset`` / ``user_password_reset_failed``) so the flows
stay filterable. All AD I/O goes through the injected client, so in the strict
split it crosses the AD-RPC boundary like every other write.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from sqlalchemy.ext.asyncio import AsyncSession

from magister_api.ad.client import AdClient
from magister_api.ad.errors import AdUnavailableError
from magister_api.ad.password import generate_password, passes_default_complexity
from magister_api.audit.service import AuditService
from magister_api.config import Settings
from magister_api.models.auth import AdUserCache
from magister_api.repositories.base import ScopeContext


class UserResetDisabledError(RuntimeError):
    """Target user's AD account is disabled — refuse the reset."""


class UserResetManualPasswordPolicyError(ValueError):
    """The manual password violates AD's default complexity policy."""


class UserResetNotInAdError(LookupError):
    """No DN was found in AD for the user's objectGUID."""


@dataclass(frozen=True)
class UserPasswordResetResult:
    mode: Literal["generate", "manual"]
    force_change: bool
    temp_password: str | None


class UserPasswordResetService:
    def __init__(
        self,
        session: AsyncSession,
        settings: Settings,
        scope: ScopeContext,
        ad: AdClient,
    ) -> None:
        self.session = session
        self.settings = settings
        self.scope = scope
        self.ad = ad
        self.audit = AuditService(session, settings)

    async def reset(
        self,
        *,
        target: AdUserCache,
        mode: Literal["generate", "manual"],
        manual_password: str | None,
        force_change: bool,
        ip: str | None,
        request_id: str,
    ) -> UserPasswordResetResult:
        if not target.enabled:
            raise UserResetDisabledError(target.ad_object_guid)

        if mode == "generate":
            new_password = generate_password()
            assert passes_default_complexity(new_password)
            response_password: str | None = new_password
        else:
            assert manual_password is not None  # schema-enforced
            if not passes_default_complexity(manual_password):
                raise UserResetManualPasswordPolicyError("manual_password_policy")
            new_password = manual_password
            response_password = None

        user_dn = await self.ad.find_user_dn(target.ad_object_guid)
        if not user_dn:
            raise UserResetNotInAdError(target.ad_object_guid)

        if mode == "manual":
            ok = await self.ad.probe_bind_as_user(user_dn=user_dn, password=new_password)
            if not ok:
                raise UserResetManualPasswordPolicyError("manual_password_rejected_by_ad")

        try:
            await self.ad.modify_password(
                user_dn=user_dn,
                new_password=new_password,
                force_change=force_change,
            )
        except AdUnavailableError:
            await self.audit.emit(
                action="user_password_reset_failed",
                target_kind="ad_user",
                target_id=target.ad_object_guid,
                actor_upn=self.scope.upn,
                actor_object_guid=self.scope.ad_object_guid,
                school_id=target.school_id,
                ip=ip,
                request_id=request_id,
                payload={"mode": mode, "force_change": force_change, "reason": "ldap_unavailable"},
            )
            raise

        await self.audit.emit(
            action="user_password_reset",
            target_kind="ad_user",
            target_id=target.ad_object_guid,
            actor_upn=self.scope.upn,
            actor_object_guid=self.scope.ad_object_guid,
            school_id=target.school_id,
            ip=ip,
            request_id=request_id,
            payload={
                "mode": mode,
                "force_change": force_change,
                "user_dn_suffix": user_dn.split(",", 1)[1] if "," in user_dn else "",
            },
        )

        # Keep the password vault in sync for opt-in users (global switch gated).
        if target.store_password:
            from magister_api.services.password_vault import PasswordVaultService

            vault = PasswordVaultService(self.session, self.settings)
            if await vault.enabled():
                await vault.store(target.ad_object_guid, new_password)

        return UserPasswordResetResult(
            mode=mode,
            force_change=force_change,
            temp_password=response_password,
        )


__all__ = [
    "UserPasswordResetResult",
    "UserPasswordResetService",
    "UserResetDisabledError",
    "UserResetManualPasswordPolicyError",
    "UserResetNotInAdError",
]
