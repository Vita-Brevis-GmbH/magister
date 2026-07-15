"""AD group catalog + optional groups search base

- ``ad_group_cache`` table — read-only mirror of the AD groups, populated by the
  full sync so the Userkonfiguration GUI can offer group DNs as checkboxes.
- ``app_settings.ad_groups_search_base`` (nullable) — optional subtree to walk
  for ``group`` objects; unset falls back to the users search base.

Revision ID: 0027_ad_group_catalog
Revises: 0026_ad_group_templates
Create Date: 2026-07-15
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0027_ad_group_catalog"
down_revision: str | Sequence[str] | None = "0026_ad_group_templates"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "app_settings",
        sa.Column("ad_groups_search_base", sa.String(length=512), nullable=True),
    )
    op.create_table(
        "ad_group_cache",
        sa.Column("ad_object_guid", sa.String(length=36), primary_key=True),
        sa.Column("distinguished_name", sa.String(length=512), nullable=False),
        sa.Column("cn", sa.String(length=256), nullable=False),
        sa.Column("sam_account_name", sa.String(length=256), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "last_sync_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_ad_group_cache_cn", "ad_group_cache", ["cn"])


def downgrade() -> None:
    op.drop_index("ix_ad_group_cache_cn", table_name="ad_group_cache")
    op.drop_table("ad_group_cache")
    op.drop_column("app_settings", "ad_groups_search_base")
