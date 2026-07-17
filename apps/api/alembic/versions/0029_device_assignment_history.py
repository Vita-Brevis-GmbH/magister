"""Device assignment history

Adds the ``device_assignments`` table: one row per assignment period (who held a
device, whether it was a loaner, and the from/to dates), so the device history
is visible and survives the holder being deleted (the ``label`` is a snapshot).

Revision ID: 0029_device_assignment_history
Revises: 0028_device_is_loan
Create Date: 2026-07-17
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0029_device_assignment_history"
down_revision: str | Sequence[str] | None = "0028_device_is_loan"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "device_assignments",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "device_id",
            sa.Integer(),
            sa.ForeignKey("devices.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("assignment_type", sa.String(length=16), nullable=False),
        sa.Column("assigned_person_guid", sa.String(length=36), nullable=True),
        sa.Column(
            "class_id",
            sa.Integer(),
            sa.ForeignKey("classes.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "school_id",
            sa.Integer(),
            sa.ForeignKey("schools.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("label", sa.String(length=320), nullable=False),
        sa.Column("is_loan", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("valid_to", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_device_assignments_device_id", "device_assignments", ["device_id"])


def downgrade() -> None:
    op.drop_index("ix_device_assignments_device_id", table_name="device_assignments")
    op.drop_table("device_assignments")
