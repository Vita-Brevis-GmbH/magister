"""department_memberships + manager_roles (M6 Phase 2)

Company-edition parallels to class_memberships / class_teacher_roles, scoped to
a department. Memberships allow multiple active rows per person (matrix orgs);
manager roles carry a role (lead/deputy) with a valid window.

Revision ID: 0035_department_people
Revises: 0034_departments
Create Date: 2026-08-21
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0035_department_people"
down_revision: str | Sequence[str] | None = "0034_departments"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "department_memberships",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "department_id",
            sa.Integer(),
            sa.ForeignKey("departments.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("ad_object_guid", sa.String(length=36), nullable=False),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("valid_to", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.String(length=320), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "valid_to IS NULL OR valid_to >= valid_from",
            name="ck_department_memberships_window",
        ),
    )
    op.create_index(
        "ix_department_memberships_department_id", "department_memberships", ["department_id"]
    )
    op.create_index(
        "ix_department_memberships_ad_object_guid", "department_memberships", ["ad_object_guid"]
    )

    op.create_table(
        "manager_roles",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "department_id",
            sa.Integer(),
            sa.ForeignKey("departments.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("ad_object_guid", sa.String(length=36), nullable=False),
        sa.Column("role", sa.String(length=32), nullable=False),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("valid_to", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.String(length=320), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("role IN ('lead', 'deputy')", name="ck_manager_roles_role"),
        sa.CheckConstraint(
            "valid_to IS NULL OR valid_to >= valid_from", name="ck_manager_roles_window"
        ),
    )
    op.create_index("ix_manager_roles_department_id", "manager_roles", ["department_id"])
    op.create_index("ix_manager_roles_ad_object_guid", "manager_roles", ["ad_object_guid"])


def downgrade() -> None:
    op.drop_index("ix_manager_roles_ad_object_guid", table_name="manager_roles")
    op.drop_index("ix_manager_roles_department_id", table_name="manager_roles")
    op.drop_table("manager_roles")
    op.drop_index("ix_department_memberships_ad_object_guid", table_name="department_memberships")
    op.drop_index("ix_department_memberships_department_id", table_name="department_memberships")
    op.drop_table("department_memberships")
