"""ad_user_cache: ad_missing_since marker for users deleted from AD

Set by a full sync when a student/teacher objectGUID is absent from AD; drives
the "should be deleted" flag in the UI. Cleared when the user reappears.

Revision ID: 0018_ad_missing_since
Revises: 0017_ad_bind_mode
Create Date: 2026-07-03
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0018_ad_missing_since"
down_revision: str | Sequence[str] | None = "0017_ad_bind_mode"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "ad_user_cache",
        sa.Column("ad_missing_since", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_ad_user_cache_ad_missing_since", "ad_user_cache", ["ad_missing_since"])


def downgrade() -> None:
    op.drop_index("ix_ad_user_cache_ad_missing_since", table_name="ad_user_cache")
    op.drop_column("ad_user_cache", "ad_missing_since")
