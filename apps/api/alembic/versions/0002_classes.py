"""classes: school class CRUD + soft-delete via status

Revision ID: 0002_classes
Revises: 0001_foundation
Create Date: 2026-04-30
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0002_classes"
down_revision: str | Sequence[str] | None = "0001_foundation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "classes",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "school_id",
            sa.Integer(),
            sa.ForeignKey("schools.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("kuerzel", sa.String(length=32), nullable=True),
        sa.Column("jahrgangsstufe", sa.Integer(), nullable=False),
        sa.Column(
            "status", sa.String(length=16), nullable=False, server_default=sa.text("'active'")
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint("status IN ('active', 'archived')", name="ck_classes_status"),
    )
    op.create_index("ix_classes_school_id", "classes", ["school_id"])
    # An active class name must be unique within a school. Archived classes are
    # excluded so a re-created class can reuse a freed name.
    op.execute(
        "CREATE UNIQUE INDEX ix_classes_school_active_name "
        "ON classes (school_id, name) WHERE status = 'active'"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_classes_school_active_name")
    op.drop_index("ix_classes_school_id", table_name="classes")
    op.drop_table("classes")
