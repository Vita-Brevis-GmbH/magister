"""Second factor (TOTP) for the local break-glass account (ADR-0015 D2)

The local admin was the last login path without a second factor. Adds RFC-6238
TOTP state plus the bookkeeping the four reset actions need:

- ``local_admins.totp_secret_enc``     (bytea)  — pgcrypto-encrypted shared secret
- ``local_admins.totp_confirmed_at``   (tstz)   — NULL = enrolment not finished
- ``local_admins.totp_last_step``      (bigint) — last accepted time step (replay guard)
- ``local_admins.recovery_codes``      (jsonb)  — argon2id hashes, single-use
- ``local_admins.totp_reset_at``       (tstz)   — when the factor was last cleared
- ``local_admins.totp_reset_by``       (text)   — who cleared it
- ``local_admins.mfa_suspended_until`` (tstz)   — time-boxed emergency bypass
- ``local_admins.mfa_failed_count``    (int)    — failed second-factor attempts

``mfa_failed_count`` is deliberately *not* ``failed_login_count``: a correct
password resets that one, so counting code failures there would let anyone who
has the password retry the second factor for ever. Two budgets, one lockout.

No data migration: an existing account has a NULL secret and is therefore
"not enrolled", which the login flow turns into a forced enrolment.

Revision ID: 0044_local_admin_totp
Revises: 0043_ninja_connector
Create Date: 2026-09-08
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0044_local_admin_totp"
down_revision: str | Sequence[str] | None = "0043_ninja_connector"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("local_admins", sa.Column("totp_secret_enc", sa.LargeBinary(), nullable=True))
    op.add_column(
        "local_admins", sa.Column("totp_confirmed_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column("local_admins", sa.Column("totp_last_step", sa.BigInteger(), nullable=True))
    op.add_column(
        "local_admins",
        sa.Column(
            "recovery_codes",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="[]",
        ),
    )
    op.add_column(
        "local_admins", sa.Column("totp_reset_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column("local_admins", sa.Column("totp_reset_by", sa.String(length=320), nullable=True))
    op.add_column(
        "local_admins", sa.Column("mfa_suspended_until", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "local_admins",
        sa.Column("mfa_failed_count", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("local_admins", "mfa_failed_count")
    op.drop_column("local_admins", "mfa_suspended_until")
    op.drop_column("local_admins", "totp_reset_by")
    op.drop_column("local_admins", "totp_reset_at")
    op.drop_column("local_admins", "recovery_codes")
    op.drop_column("local_admins", "totp_last_step")
    op.drop_column("local_admins", "totp_confirmed_at")
    op.drop_column("local_admins", "totp_secret_enc")
