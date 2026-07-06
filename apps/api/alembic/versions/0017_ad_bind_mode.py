"""app_settings: GUI-toggleable AD service bind mode (simple | gssapi)

Adds ad_bind_mode (default 'simple') so the Kerberos/GSSAPI bind can be enabled
from the admin settings UI. See ADR 0007.

Revision ID: 0017_ad_bind_mode
Revises: 0016_zyklus_boundaries
Create Date: 2026-07-03
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0017_ad_bind_mode"
down_revision: str | Sequence[str] | None = "0016_zyklus_boundaries"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "app_settings",
        sa.Column("ad_bind_mode", sa.String(16), nullable=False, server_default="simple"),
    )


def downgrade() -> None:
    op.drop_column("app_settings", "ad_bind_mode")
