"""departments: mid-level org unit for the company edition (M6 Phase 2)

Parallel to ``classes`` (ADR-0008 D6). Scoped by ``school_id`` (the physical
top-level scope column). Active-only name uniqueness per org unit via a partial
unique index, mirroring classes.

Revision ID: 0034_departments
Revises: 0033_module_settings
Create Date: 2026-08-21
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0034_departments"
down_revision: str | Sequence[str] | None = "0033_module_settings"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "departments",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "school_id",
            sa.Integer(),
            sa.ForeignKey("schools.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("kuerzel", sa.String(length=32), nullable=True),
        sa.Column("details", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="active"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('active', 'archived')", name="ck_departments_status"
        ),
    )
    op.create_index("ix_departments_school_id", "departments", ["school_id"])
    op.create_index(
        "ix_departments_school_active_name",
        "departments",
        ["school_id", "name"],
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
    )


def downgrade() -> None:
    op.drop_index("ix_departments_school_active_name", table_name="departments")
    op.drop_index("ix_departments_school_id", table_name="departments")
    op.drop_table("departments")
