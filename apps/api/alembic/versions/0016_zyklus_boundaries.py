"""app_settings: configurable Zyklus boundaries by Jahrgangsstufe

Adds zyklus1_max_grade (default 2) and zyklus2_max_grade (default 6). Zyklus 3
is everything above zyklus2_max_grade. Drives the student-provisioning target OU.

Revision ID: 0016_zyklus_boundaries
Revises: 0015_provisioning_ous
Create Date: 2026-07-03
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0016_zyklus_boundaries"
down_revision: str | Sequence[str] | None = "0015_provisioning_ous"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "app_settings",
        sa.Column("zyklus1_max_grade", sa.Integer(), nullable=False, server_default="2"),
    )
    op.add_column(
        "app_settings",
        sa.Column("zyklus2_max_grade", sa.Integer(), nullable=False, server_default="6"),
    )


def downgrade() -> None:
    op.drop_column("app_settings", "zyklus2_max_grade")
    op.drop_column("app_settings", "zyklus1_max_grade")
