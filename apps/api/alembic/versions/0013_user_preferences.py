"""per-user UI preferences (language, region, formats)

A small self-service preferences table keyed by the authenticated user's
objectGUID. Only staff (teachers/admin) authenticate, so this never holds
student rows. All columns have sensible defaults so a missing row reads as
the Swiss-German defaults.

Revision ID: 0013_user_preferences
Revises: 0012_class_details
Create Date: 2026-06-30
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0013_user_preferences"
down_revision: str | Sequence[str] | None = "0012_class_details"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "user_preferences",
        sa.Column("ad_object_guid", sa.String(length=36), primary_key=True),
        sa.Column("language", sa.String(length=8), nullable=False, server_default="de"),
        sa.Column("region", sa.String(length=16), nullable=False, server_default="CH"),
        sa.Column("date_format", sa.String(length=32), nullable=False, server_default="DD.MM.YYYY"),
        sa.Column("time_format", sa.String(length=8), nullable=False, server_default="24h"),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )


def downgrade() -> None:
    op.drop_table("user_preferences")
