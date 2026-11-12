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
from magister_api.ad.errors import AdUnavailableError, is_password_rejected
from magister_api.ad.password import generate_for_profile, passes_default_complexity
from magister_api.audit.service import AuditService
from magister_api.config import Settings
from magister_api.models.auth import AdUserCache
from magister_api.repositories.base import ScopeContext
from magister_api.services.zielgruppen import password_profile_for


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
            # Passwortart der Zielgruppe des Kontos (sonst nach Kontoart).
            profile = await password_profile_for(self.session, target)
            new_password = generate_for_profile(profile)
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

        try:
            await self.ad.modify_password(
                user_dn=user_dn,
                new_password=new_password,
                force_change=force_change,
            )
        except AdUnavailableError as exc:
            rejected = is_password_rejected(exc)
            await self.audit.emit(
                action="user_password_reset_failed",
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
                    "reason": "password_rejected_by_ad" if rejected else "ldap_unavailable",
                },
            )
            if rejected:
                # Das AD hat das Passwort abgelehnt (Richtlinie, Verlauf,
                # Mindestalter) — eine Antwort an den Menschen, kein Ausfall.
                raise UserResetManualPasswordPolicyError("manual_password_rejected_by_ad") from exc
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
        # Nur ein Passwort, das so bleibt, kommt in den Tresor; ein Reset mit
        # erzwungener Änderung macht die alte Kopie falsch — die fällt weg.
        if target.store_password:
            from magister_api.services.password_vault import (
                PasswordVaultService,
                password_stays,
            )

            vault = PasswordVaultService(self.session, self.settings)
            if not password_stays(
                force_change=force_change,
                cannot_change_password=target.cannot_change_password,
                password_never_expires=target.password_never_expires,
            ):
                await vault.clear(target.ad_object_guid)
            elif await vault.enabled():
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
