"""app_settings: instance_profile + per-module enable overrides (M6 Phase 1)

Adds the soft instance profile (school/company/neutral) that seeds the default
module set + vocabulary, and the per-module override map that is the source of
truth for which feature modules are enabled. See ADR-0008.

Revision ID: 0033_module_settings
Revises: 0032_ad_missing_since
Create Date: 2026-08-21
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0033_module_settings"
down_revision: str | Sequence[str] | None = "0032_ad_missing_since"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "app_settings",
        sa.Column(
            "instance_profile",
            sa.String(length=16),
            nullable=False,
            server_default="school",
        ),
    )
    op.add_column(
        "app_settings",
        sa.Column(
            "module_overrides",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )


def downgrade() -> None:
    op.drop_column("app_settings", "module_overrides")
    op.drop_column("app_settings", "instance_profile")
