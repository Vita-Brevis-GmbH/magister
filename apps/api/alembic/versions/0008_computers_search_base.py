"""ad_computers_search_base on app_settings (Phase 4 device sync).

Adds one nullable column to ``app_settings``: the LDAP search base under
which the AD-sync looks for ``Computer`` objects with ``managedBy`` set.
Empty/unset = device sync is skipped silently (the feature is optional
per the spec).

Revision ID: 0008_computers_search_base
Revises: 0007_user_attrs
Create Date: 2026-05-22
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0008_computers_search_base"
down_revision: str | Sequence[str] | None = "0007_user_attrs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "app_settings",
        sa.Column("ad_computers_search_base", sa.String(length=512), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("app_settings", "ad_computers_search_base")
