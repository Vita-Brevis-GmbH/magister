"""Student password-reset orchestration.

Per CLAUDE.md "Niemals"-Regel and SPEC.md §6: the temporary password is
returned to the requesting KL exactly once in the HTTP response and is
never written to the audit log. The audit-payload allowlist would already
reject it (key contains "password"), but we double-check by hand-crafting
an explicit payload that omits any plaintext.
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


class StudentDisabledError(RuntimeError):
    """Target student's AD account is disabled — refuse the reset."""


class ManualPasswordPolicyError(ValueError):
    """The manual password violates AD's default complexity policy."""


class StudentNotInAdError(LookupError):
    """No DN was found in AD for the student's objectGUID."""


@dataclass(frozen=True)
class PasswordResetResult:
    mode: Literal["generate", "manual"]
    force_change: bool
    temp_password: str | None


class StudentPasswordResetService:
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
        student: AdUserCache,
        mode: Literal["generate", "manual"],
        manual_password: str | None,
        force_change: bool,
        ip: str | None,
        request_id: str,
    ) -> PasswordResetResult:
        if not student.enabled:
            raise StudentDisabledError(student.ad_object_guid)

        # 1) Determine the password we'll write.
        if mode == "generate":
            new_password = generate_password()
            assert passes_default_complexity(new_password)
            response_password: str | None = new_password
        else:
            assert manual_password is not None  # schema-enforced
            if not passes_default_complexity(manual_password):
                raise ManualPasswordPolicyError("manual_password_policy")
            new_password = manual_password
            response_password = None

        # 2) Resolve the student's DN.
        user_dn = await self.ad.find_user_dn(student.ad_object_guid)
        if not user_dn:
            raise StudentNotInAdError(student.ad_object_guid)

        # 3) Probe-bind in manual mode to surface AD-side policy violations
        # before we touch unicodePwd.
        if mode == "manual":
            ok = await self.ad.probe_bind_as_user(user_dn=user_dn, password=new_password)
            if not ok:
                raise ManualPasswordPolicyError("manual_password_rejected_by_ad")

        # 4) Write the password. This may raise AdUnavailableError; the
        # router translates it to 503. The audit MUST run even on failure
        # of the actual modify so operators see the attempt.
        try:
            await self.ad.modify_password(
                user_dn=user_dn,
                new_password=new_password,
                force_change=force_change,
            )
        except AdUnavailableError:
            await self.audit.emit(
                action="student_password_reset_failed",
                target_kind="ad_user",
                target_id=student.ad_object_guid,
                actor_upn=self.scope.upn,
                actor_object_guid=self.scope.ad_object_guid,
                school_id=student.school_id,
                ip=ip,
                request_id=request_id,
                payload={
                    "mode": mode,
                    "force_change": force_change,
                    "reason": "ldap_unavailable",
                },
            )
            raise

        # 5) Success audit. Payload deliberately excludes the plaintext;
        # the allowlist would reject it but we belt-and-braces it here.
        await self.audit.emit(
            action="student_password_reset",
            target_kind="ad_user",
            target_id=student.ad_object_guid,
            actor_upn=self.scope.upn,
            actor_object_guid=self.scope.ad_object_guid,
            school_id=student.school_id,
            ip=ip,
            request_id=request_id,
            payload={
                "mode": mode,
                "force_change": force_change,
                "user_dn_suffix": user_dn.split(",", 1)[1] if "," in user_dn else "",
            },
        )

        # Keep the password vault in sync for opt-in users (global switch gated).
        if student.store_password:
            from magister_api.services.password_vault import PasswordVaultService

            vault = PasswordVaultService(self.session, self.settings)
            if await vault.enabled():
                await vault.store(student.ad_object_guid, new_password)

        return PasswordResetResult(
            mode=mode,
            force_change=force_change,
            temp_password=response_password,
        )


__all__ = [
    "ManualPasswordPolicyError",
    "PasswordResetResult",
    "StudentDisabledError",
    "StudentNotInAdError",
    "StudentPasswordResetService",
]
