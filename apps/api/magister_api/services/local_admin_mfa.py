"""Second factor for the local break-glass account (ADR-0015 D2).

Kept apart from :class:`~magister_api.services.local_admin.LocalAdminService`
because it needs the pgcrypto key (and therefore ``Settings``) while the
password path does not — and because the four reset actions are a concern of
their own.

Two properties this module exists to guarantee:

1. **A reset never reveals a secret.** :meth:`reset` only clears; the new
   secret is generated during the next enrolment, by whoever logs in. An
   operator cannot mint a working second factor for themselves.
2. **The MFA requirement can only be suspended with an expiry.** There is no
   "off" — :meth:`suspend_requirement` always writes a deadline, and it lapses
   on its own.

Audit events are the caller's job (they are per-route / per-CLI), matching the
existing local-admin service.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import timedelta
from enum import StrEnum

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from magister_api.auth import totp
from magister_api.auth.passwords import hash_password, verify_password
from magister_api.config import Settings
from magister_api.models.base import utcnow
from magister_api.models.local_admin import LocalAdmin
from magister_api.services.local_admin import LOCKOUT_DURATION, MAX_FAILED_ATTEMPTS

logger = logging.getLogger(__name__)

#: What the authenticator app shows next to the code.
TOTP_ISSUER = "Magister"

#: How long an emergency bypass lasts. Not configurable on purpose: a value an
#: operator can raise is a value that ends up at "1 year".
MFA_SUSPENSION = timedelta(hours=24)


class MfaAlreadyEnrolledError(RuntimeError):
    """Raised when enrolment is attempted while a confirmed factor exists."""


class MfaStage(StrEnum):
    """What the login flow must do after the password checked out."""

    #: Confirmed second factor present — ask for a code.
    TOTP = "totp"
    #: No confirmed factor — force enrolment before issuing a session.
    ENROLL = "enroll"
    #: Requirement suspended and the window is still open — password suffices.
    SUSPENDED = "suspended"


@dataclass(frozen=True)
class EnrollmentOffer:
    """Everything the SPA needs to render the enrolment step."""

    secret: str
    provisioning_uri: str
    qr_data_uri: str


@dataclass(frozen=True)
class MfaStatus:
    """Read-only view for the admin surface and the CLI."""

    enrolled: bool
    recovery_codes_left: int
    reset_at: object | None
    reset_by: str | None
    suspended_until: object | None


class LocalAdminMfaService:
    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self.session = session
        self._settings = settings

    @property
    def _key(self) -> str:
        key = self._settings.audit_key.get_secret_value()
        if not key:
            raise RuntimeError("MAGISTER_AUDIT_KEY is empty — TOTP storage refused")
        return key

    # ---------- state ----------

    def stage_for(self, admin: LocalAdmin) -> MfaStage:
        """Which login stage follows a correct password for *admin*."""
        if not self._settings.local_mfa_required:
            return MfaStage.SUSPENDED
        until = admin.mfa_suspended_until
        if until is not None and until > utcnow():
            return MfaStage.SUSPENDED
        if admin.totp_confirmed_at is not None and admin.totp_secret_enc is not None:
            return MfaStage.TOTP
        return MfaStage.ENROLL

    async def status(self) -> MfaStatus | None:
        row = (
            await self.session.execute(
                select(
                    LocalAdmin.totp_confirmed_at,
                    LocalAdmin.recovery_codes,
                    LocalAdmin.totp_reset_at,
                    LocalAdmin.totp_reset_by,
                    LocalAdmin.mfa_suspended_until,
                ).where(LocalAdmin.id == 1)
            )
        ).one_or_none()
        if row is None:
            return None
        return MfaStatus(
            enrolled=row.totp_confirmed_at is not None,
            recovery_codes_left=len(row.recovery_codes or []),
            reset_at=row.totp_reset_at,
            reset_by=row.totp_reset_by,
            suspended_until=row.mfa_suspended_until,
        )

    # ---------- enrolment ----------

    async def begin_enrollment(self, *, account: str) -> EnrollmentOffer:
        """Generate and store a *pending* secret, and return it once.

        Replaces any earlier pending secret (a restarted enrolment is normal).
        Refuses to touch a confirmed one — that path is :meth:`reset`.
        """
        confirmed = (
            await self.session.execute(
                select(LocalAdmin.totp_confirmed_at).where(LocalAdmin.id == 1)
            )
        ).scalar_one_or_none()
        if confirmed is not None:
            raise MfaAlreadyEnrolledError

        secret = totp.new_secret()
        await self.session.execute(
            update(LocalAdmin)
            .where(LocalAdmin.id == 1)
            .values(
                totp_secret_enc=func.pgp_sym_encrypt(secret, self._key),
                totp_confirmed_at=None,
                totp_last_step=None,
            )
        )
        await self.session.flush()
        uri = totp.provisioning_uri(secret, account=account, issuer=TOTP_ISSUER)
        return EnrollmentOffer(
            secret=secret, provisioning_uri=uri, qr_data_uri=totp.qr_data_uri(uri)
        )

    async def confirm_enrollment(self, code: str) -> list[str] | None:
        """Finish enrolment; return the plaintext recovery codes, shown once.

        ``None`` means the code did not verify (or nothing is pending).
        """
        secret = await self._pending_secret()
        if secret is None:
            return None
        step = totp.verify_code(secret, code, last_step=None)
        if step is None:
            return None

        codes = totp.new_recovery_codes()
        await self.session.execute(
            update(LocalAdmin)
            .where(LocalAdmin.id == 1)
            .values(
                totp_confirmed_at=utcnow(),
                totp_last_step=step,
                recovery_codes=[hash_password(c) for c in codes],
                totp_reset_at=None,
                totp_reset_by=None,
                mfa_suspended_until=None,
                mfa_failed_count=0,
            )
        )
        await self.session.flush()
        return codes

    # ---------- verification ----------

    async def verify(self, code: str) -> bool:
        """Check *code* as a TOTP code or, failing that, a recovery code.

        A wrong code counts on the same ``failed_login_count`` as a wrong
        password, so five wrong codes trip the existing 15-minute lockout — an
        attacker who has the password does not get unlimited attempts at the
        second factor.
        """
        row = (
            await self.session.execute(
                select(
                    func.pgp_sym_decrypt(LocalAdmin.totp_secret_enc, self._key).label("secret"),
                    LocalAdmin.totp_last_step,
                    LocalAdmin.recovery_codes,
                    LocalAdmin.totp_confirmed_at,
                ).where(LocalAdmin.id == 1)
            )
        ).one_or_none()
        if row is None or row.totp_confirmed_at is None or not row.secret:
            return False

        step = totp.verify_code(row.secret, code, last_step=row.totp_last_step)
        if step is not None:
            await self.session.execute(
                update(LocalAdmin)
                .where(LocalAdmin.id == 1)
                .values(totp_last_step=step, mfa_failed_count=0)
            )
            await self.session.flush()
            return True

        remaining = await self._consume_recovery_code(code, list(row.recovery_codes or []))
        if remaining is not None:
            logger.warning(
                "Local admin signed in with a recovery code — %d of %d left.",
                len(remaining),
                totp.RECOVERY_CODE_COUNT,
            )
            return True

        await self._count_failure()
        return False

    async def _consume_recovery_code(self, code: str, hashes: list[str]) -> list[str] | None:
        """Burn a matching recovery code; return the remaining hashes, else None."""
        candidate = totp.normalize_recovery_code(code)
        if not candidate:
            return None
        for stored in hashes:
            if verify_password(candidate, stored):
                remaining = [h for h in hashes if h != stored]
                await self.session.execute(
                    update(LocalAdmin).where(LocalAdmin.id == 1).values(recovery_codes=remaining)
                )
                await self.session.flush()
                return remaining
        return None

    async def _count_failure(self) -> None:
        """Count a wrong code and trip the shared lockout at the threshold.

        Uses ``mfa_failed_count``, not ``failed_login_count``: a correct
        password resets the latter, so counting there would hand anyone who has
        the password unlimited attempts at the second factor. On tripping, the
        counter resets — the 15-minute lock is the penalty, and the next window
        starts fresh.
        """
        await self.session.execute(
            update(LocalAdmin)
            .where(LocalAdmin.id == 1)
            .values(mfa_failed_count=LocalAdmin.mfa_failed_count + 1)
        )
        await self.session.flush()
        count = (
            await self.session.execute(
                select(LocalAdmin.mfa_failed_count).where(LocalAdmin.id == 1)
            )
        ).scalar_one_or_none()
        if count is not None and count >= MAX_FAILED_ATTEMPTS:
            await self.session.execute(
                update(LocalAdmin)
                .where(LocalAdmin.id == 1)
                .values(locked_until=utcnow() + LOCKOUT_DURATION, mfa_failed_count=0)
            )
            await self.session.flush()

    # ---------- the four reset actions (ADR-0015 D2) ----------

    async def reset(self, *, actor: str) -> bool:
        """Clear the second factor entirely; the next login forces enrolment.

        Returns nothing secret — that is the point (see the module docstring).
        """
        exists = (
            await self.session.execute(select(LocalAdmin.id).where(LocalAdmin.id == 1))
        ).scalar_one_or_none()
        if exists is None:
            return False
        await self.session.execute(
            update(LocalAdmin)
            .where(LocalAdmin.id == 1)
            .values(
                totp_secret_enc=None,
                totp_confirmed_at=None,
                totp_last_step=None,
                recovery_codes=[],
                totp_reset_at=utcnow(),
                totp_reset_by=actor[:320],
                mfa_failed_count=0,
            )
        )
        await self.session.flush()
        return True

    async def regenerate_recovery_codes(self) -> list[str] | None:
        """A fresh set of codes, leaving the secret alone. ``None`` if not enrolled."""
        confirmed = (
            await self.session.execute(
                select(LocalAdmin.totp_confirmed_at).where(LocalAdmin.id == 1)
            )
        ).scalar_one_or_none()
        if confirmed is None:
            return None
        codes = totp.new_recovery_codes()
        await self.session.execute(
            update(LocalAdmin)
            .where(LocalAdmin.id == 1)
            .values(recovery_codes=[hash_password(c) for c in codes])
        )
        await self.session.flush()
        return codes

    async def suspend_requirement(self, *, actor: str, reason: str) -> object:
        """Let the password alone through — for 24 hours, then never again.

        The deadline is not a parameter: a duration an operator can raise is a
        duration that ends up at "1 year".
        """
        until = utcnow() + MFA_SUSPENSION
        await self.session.execute(
            update(LocalAdmin).where(LocalAdmin.id == 1).values(mfa_suspended_until=until)
        )
        await self.session.flush()
        logger.warning(
            "MFA requirement for the local admin suspended until %s by %s (%s).",
            until.isoformat(),
            actor,
            reason,
        )
        return until

    # ---------- internals ----------

    async def _pending_secret(self) -> str | None:
        row = (
            await self.session.execute(
                select(
                    func.pgp_sym_decrypt(LocalAdmin.totp_secret_enc, self._key).label("secret"),
                    LocalAdmin.totp_confirmed_at,
                ).where(LocalAdmin.id == 1)
            )
        ).one_or_none()
        if row is None or row.totp_confirmed_at is not None:
            return None
        return row.secret or None


__all__ = [
    "MFA_SUSPENSION",
    "TOTP_ISSUER",
    "EnrollmentOffer",
    "LocalAdminMfaService",
    "MfaAlreadyEnrolledError",
    "MfaStage",
    "MfaStatus",
]
