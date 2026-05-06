"""class_memberships: students assigned to classes with valid window

Revision ID: 0004_class_memberships
Revises: 0003_class_teacher_roles
Create Date: 2026-04-30
"""

from __future__ import annotations

from typing import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004_class_memberships"
down_revision: str | Sequence[str] | None = "0003_class_teacher_roles"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "class_memberships",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "class_id",
            sa.Integer(),
            sa.ForeignKey("classes.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("ad_object_guid", sa.String(length=36), nullable=False),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("valid_to", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.String(length=320), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "valid_to IS NULL OR valid_to >= valid_from",
            name="ck_class_memberships_window",
        ),
    )
    op.create_index(
        "ix_class_memberships_class_id", "class_memberships", ["class_id"]
    )
    op.create_index(
        "ix_class_memberships_ad_object_guid", "class_memberships", ["ad_object_guid"]
    )
    op.create_index(
        "ix_class_memberships_window",
        "class_memberships",
        ["ad_object_guid", "valid_from", "valid_to"],
    )


def downgrade() -> None:
    op.drop_index("ix_class_memberships_window", table_name="class_memberships")
    op.drop_index(
        "ix_class_memberships_ad_object_guid", table_name="class_memberships"
    )
    op.drop_index("ix_class_memberships_class_id", table_name="class_memberships")
    op.drop_table("class_memberships")
