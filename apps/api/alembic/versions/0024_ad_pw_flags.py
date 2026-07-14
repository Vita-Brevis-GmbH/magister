"""ad_user_cache: password_never_expires + cannot_change_password flags

Two AD account-policy flags surfaced in Magister:
- ``password_never_expires`` mirrors the userAccountControl DONT_EXPIRE_PASSWD
  bit (round-tripped by the AD sync).
- ``cannot_change_password`` is Magister-tracked intent, enforced in AD via the
  object's DACL; the sync does not read it back.

Both default to false (server_default) so existing rows stay valid.

Revision ID: 0024_ad_pw_flags
Revises: 0023_student_jahrgangsstufe
Create Date: 2026-07-14
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0024_ad_pw_flags"
down_revision: str | Sequence[str] | None = "0023_student_jahrgangsstufe"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "ad_user_cache",
        sa.Column(
            "password_never_expires",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.add_column(
        "ad_user_cache",
        sa.Column(
            "cannot_change_password",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )


def downgrade() -> None:
    op.drop_column("ad_user_cache", "cannot_change_password")
    op.drop_column("ad_user_cache", "password_never_expires")
