"""ad_sync_state singleton

Revision ID: 0010_ad_sync_state
Revises: 0009_import_jobs
Create Date: 2026-06-02

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0010_ad_sync_state"
down_revision: str | None = "0009_import_jobs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "ad_sync_state",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("last_when_changed", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_full_sync_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_synced_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_mode", sa.String(16), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint("id = 1", name="ck_ad_sync_state_singleton"),
    )


def downgrade() -> None:
    op.drop_table("ad_sync_state")
