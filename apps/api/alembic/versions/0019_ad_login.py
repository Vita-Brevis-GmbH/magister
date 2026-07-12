"""app_settings: direct AD-credential login (master switch + authorizing group)

Adds two columns so admins can enable password-based AD login (LDAPS bind)
alongside Entra/OIDC:

- ``ad_login_enabled`` — master switch (default false).
- ``ad_login_group``   — AD group (DN or CN) whose members may sign in that way.

Revision ID: 0019_ad_login
Revises: 0018_ad_tls
Create Date: 2026-07-12
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0019_ad_login"
down_revision: str | Sequence[str] | None = "0018_ad_tls"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "app_settings",
        sa.Column("ad_login_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "app_settings",
        sa.Column("ad_login_group", sa.String(512), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("app_settings", "ad_login_group")
    op.drop_column("app_settings", "ad_login_enabled")
