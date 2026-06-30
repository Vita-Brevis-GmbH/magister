"""subject_teacher_roles: Fachlehrer assignment (teacher + class + subject)

A subject teacher (Fachlehrer) is linked to a class with a subject and a
valid window. Kept separate from class_teacher_roles so it never feeds the
KL-authority logic (substitutions view, workload report) — but it DOES grant
student-password-reset for the students of that class.

Revision ID: 0014_subject_teacher_roles
Revises: 0013_user_preferences
Create Date: 2026-06-30
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0014_subject_teacher_roles"
down_revision: str | Sequence[str] | None = "0013_user_preferences"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "subject_teacher_roles",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "class_id",
            sa.Integer(),
            sa.ForeignKey("classes.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("ad_object_guid", sa.String(length=36), nullable=False),
        sa.Column("subject", sa.String(length=100), nullable=False),
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
            name="ck_subject_teacher_roles_window",
        ),
    )
    op.create_index("ix_subject_teacher_roles_class_id", "subject_teacher_roles", ["class_id"])
    op.create_index(
        "ix_subject_teacher_roles_ad_object_guid", "subject_teacher_roles", ["ad_object_guid"]
    )
    op.create_index(
        "ix_subject_teacher_roles_window",
        "subject_teacher_roles",
        ["class_id", "valid_from", "valid_to"],
    )


def downgrade() -> None:
    op.drop_index("ix_subject_teacher_roles_window", table_name="subject_teacher_roles")
    op.drop_index("ix_subject_teacher_roles_ad_object_guid", table_name="subject_teacher_roles")
    op.drop_index("ix_subject_teacher_roles_class_id", table_name="subject_teacher_roles")
    op.drop_table("subject_teacher_roles")
