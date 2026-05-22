"""Teacher password-reset orchestration.

Mirror of :mod:`magister_api.services.student_password_reset` for the SMI
role. Same allowlist / no-plaintext-in-audit guarantees apply; the only
deltas are the target ``kind`` check (``teacher``) and the audit action
names (``teacher_password_reset`` / ``teacher_password_reset_failed``) so
operators can filter the two reset flows separately.
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


class TeacherDisabledError(RuntimeError):
    """Target teacher's AD account is disabled — refuse the reset."""


class TeacherManualPasswordPolicyError(ValueError):
    """The manual password violates AD's default complexity policy."""


class TeacherNotInAdError(LookupError):
    """No DN was found in AD for the teacher's objectGUID."""


@dataclass(frozen=True)
class TeacherPasswordResetResult:
    mode: Literal["generate", "manual"]
    force_change: bool
    temp_password: str | None


class TeacherPasswordResetService:
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
        teacher: AdUserCache,
        mode: Literal["generate", "manual"],
        manual_password: str | None,
        force_change: bool,
        ip: str | None,
        request_id: str,
    ) -> TeacherPasswordResetResult:
        if not teacher.enabled:
            raise TeacherDisabledError(teacher.ad_object_guid)

        if mode == "generate":
            new_password = generate_password()
            assert passes_default_complexity(new_password)
            response_password: str | None = new_password
        else:
            assert manual_password is not None  # schema-enforced
            if not passes_default_complexity(manual_password):
                raise TeacherManualPasswordPolicyError("manual_password_policy")
            new_password = manual_password
            response_password = None

        user_dn = await self.ad.find_user_dn(teacher.ad_object_guid)
        if not user_dn:
            raise TeacherNotInAdError(teacher.ad_object_guid)

        if mode == "manual":
            ok = await self.ad.probe_bind_as_user(user_dn=user_dn, password=new_password)
            if not ok:
                raise TeacherManualPasswordPolicyError("manual_password_rejected_by_ad")

        try:
            await self.ad.modify_password(
                user_dn=user_dn,
                new_password=new_password,
                force_change=force_change,
            )
        except AdUnavailableError:
            await self.audit.emit(
                action="teacher_password_reset_failed",
                target_kind="ad_user",
                target_id=teacher.ad_object_guid,
                actor_upn=self.scope.upn,
                actor_object_guid=self.scope.ad_object_guid,
                school_id=teacher.school_id,
                ip=ip,
                request_id=request_id,
                payload={
                    "mode": mode,
                    "force_change": force_change,
                    "reason": "ldap_unavailable",
                },
            )
            raise

        await self.audit.emit(
            action="teacher_password_reset",
            target_kind="ad_user",
            target_id=teacher.ad_object_guid,
            actor_upn=self.scope.upn,
            actor_object_guid=self.scope.ad_object_guid,
            school_id=teacher.school_id,
            ip=ip,
            request_id=request_id,
            payload={
                "mode": mode,
                "force_change": force_change,
                "user_dn_suffix": user_dn.split(",", 1)[1] if "," in user_dn else "",
            },
        )

        return TeacherPasswordResetResult(
            mode=mode,
            force_change=force_change,
            temp_password=response_password,
        )


__all__ = [
    "TeacherDisabledError",
    "TeacherManualPasswordPolicyError",
    "TeacherNotInAdError",
    "TeacherPasswordResetResult",
    "TeacherPasswordResetService",
]
