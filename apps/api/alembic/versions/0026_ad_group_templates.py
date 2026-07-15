"""AD group templates for provisioning + synced group memberships

- ``app_settings.ad_groups_{teacher,student_zyklus1,student_zyklus2,student_zyklus3}``
  (JSONB list of group DNs) — default groups added to newly provisioned accounts.
- ``ad_user_cache.ad_groups`` (JSONB list) — memberOf DNs refreshed on sync.

All default to ``[]``.

Revision ID: 0026_ad_group_templates
Revises: 0025_password_vault
Create Date: 2026-07-14
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision: str = "0026_ad_group_templates"
down_revision: str | Sequence[str] | None = "0025_password_vault"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_GROUP_COLS = (
    "ad_groups_teacher",
    "ad_groups_student_zyklus1",
    "ad_groups_student_zyklus2",
    "ad_groups_student_zyklus3",
)


def upgrade() -> None:
    for col in _GROUP_COLS:
        op.add_column(
            "app_settings",
            sa.Column(col, JSONB(), nullable=False, server_default="[]"),
        )
    op.add_column(
        "ad_user_cache",
        sa.Column("ad_groups", JSONB(), nullable=False, server_default="[]"),
    )


def downgrade() -> None:
    op.drop_column("ad_user_cache", "ad_groups")
    for col in _GROUP_COLS:
        op.drop_column("app_settings", col)
