"""Local break-glass admin account.

A single row (``id=1``) stores the username + argon2id password hash for the
local-login path. Lockout state lives on the row so it survives a worker
restart. The actual session, once issued, is the same `Session` model the
OIDC flow uses — distinguished by ``auth_kind='local'`` and the sentinel
``ad_object_guid`` defined in ``services.local_admin``.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Integer,
    LargeBinary,
    String,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from magister_api.models.base import Base, utcnow


class LocalAdmin(Base):
    __tablename__ = "local_admins"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)  # always 1 in M1.5
    username: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    failed_login_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    password_changed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), default=utcnow, nullable=False
    )

    # --- Second factor, RFC 6238 (ADR-0015 D2) -------------------------------
    # The shared secret is pgcrypto-encrypted with MAGISTER_AUDIT_KEY, like the
    # other secret columns. ``totp_confirmed_at`` NULL means enrolment was
    # started but not finished — the login flow then forces enrolment and
    # issues no session, so there is no half-privileged state to guard for.
    totp_secret_enc: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    totp_confirmed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Last accepted 30-second step. A code is single-use: replaying it inside
    # its own window is refused.
    totp_last_step: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    # argon2id hashes of the ten single-use recovery codes. The plaintext is
    # shown once at enrolment and never stored.
    recovery_codes: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list, server_default="[]"
    )
    totp_reset_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    totp_reset_by: Mapped[str | None] = mapped_column(String(320), nullable=True)
    # Time-boxed emergency bypass: while this is in the future, the password
    # alone is enough. It always expires on its own — there is no way to extend
    # it other than granting a fresh window, and that is audited again.
    mfa_suspended_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Failed second-factor attempts. Deliberately separate from
    # ``failed_login_count``: a correct password resets that one, so counting
    # code failures there would give anyone holding the password unlimited
    # tries at the second factor. Two budgets, one shared lockout.
    mfa_failed_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )

    __table_args__ = (CheckConstraint("id = 1", name="local_admin_singleton"),)
