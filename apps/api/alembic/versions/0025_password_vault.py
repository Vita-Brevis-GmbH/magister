"""Password vault: per-user store flag + encrypted password + global toggle

- ``ad_user_cache.store_password`` (BOOL) — per-user opt-in.
- ``ad_user_cache.password_enc`` (BYTEA) — pgcrypto-encrypted stored password.
- ``app_settings.password_store_enabled`` (BOOL) — global master switch.

All default to off / NULL, so existing rows stay valid.

Revision ID: 0025_password_vault
Revises: 0024_ad_pw_flags
Create Date: 2026-07-14
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0025_password_vault"
down_revision: str | Sequence[str] | None = "0024_ad_pw_flags"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "ad_user_cache",
        sa.Column("store_password", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "ad_user_cache",
        sa.Column("password_enc", sa.LargeBinary(), nullable=True),
    )
    op.add_column(
        "app_settings",
        sa.Column(
            "password_store_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )


def downgrade() -> None:
    op.drop_column("app_settings", "password_store_enabled")
    op.drop_column("ad_user_cache", "password_enc")
    op.drop_column("ad_user_cache", "store_password")
