"""devices: Magister-managed device inventory with person/class/school binding

Devices are imported from the AD Computer-OU by name (objectGUID kept as the
stable import identity), while all extra attributes and the assignment to a
person, class or school are managed in Magister — never written back to AD.

Revision ID: 0020_devices
Revises: 0019_ad_login
Create Date: 2026-07-13
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0020_devices"
down_revision: str | Sequence[str] | None = "0019_ad_login"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "devices",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("device_type", sa.String(length=64), nullable=True),
        sa.Column("serial_number", sa.String(length=128), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "school_id",
            sa.Integer(),
            sa.ForeignKey("schools.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "class_id",
            sa.Integer(),
            sa.ForeignKey("classes.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("assigned_person_guid", sa.String(length=36), nullable=True),
        sa.Column("ad_object_guid", sa.String(length=36), nullable=True),
        sa.Column(
            "source",
            sa.String(length=16),
            nullable=False,
            server_default="manual",
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
        sa.UniqueConstraint("ad_object_guid", name="uq_devices_ad_object_guid"),
    )
    op.create_index("ix_devices_school_id", "devices", ["school_id"])
    op.create_index("ix_devices_class_id", "devices", ["class_id"])
    op.create_index("ix_devices_assigned_person_guid", "devices", ["assigned_person_guid"])


def downgrade() -> None:
    op.drop_index("ix_devices_assigned_person_guid", table_name="devices")
    op.drop_index("ix_devices_class_id", table_name="devices")
    op.drop_index("ix_devices_school_id", table_name="devices")
    op.drop_table("devices")
