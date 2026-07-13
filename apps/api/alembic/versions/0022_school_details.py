"""schools: postal address, phone, description and map coordinates

Adds contact/address fields so schools can be managed in the admin UI:
street, postal_code, city, phone, description, latitude, longitude, plus an
``updated_at`` column. All nullable / additive — existing rows stay valid.

Revision ID: 0022_school_details
Revises: 0021_class_grade_range
Create Date: 2026-07-13
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0022_school_details"
down_revision: str | Sequence[str] | None = "0021_class_grade_range"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("schools", sa.Column("street", sa.String(length=200), nullable=True))
    op.add_column("schools", sa.Column("postal_code", sa.String(length=20), nullable=True))
    op.add_column("schools", sa.Column("city", sa.String(length=120), nullable=True))
    op.add_column("schools", sa.Column("phone", sa.String(length=50), nullable=True))
    op.add_column("schools", sa.Column("description", sa.Text(), nullable=True))
    op.add_column("schools", sa.Column("latitude", sa.Float(), nullable=True))
    op.add_column("schools", sa.Column("longitude", sa.Float(), nullable=True))
    op.add_column(
        "schools",
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )

    # Audit events reference the school only as a scoping hint. Keep the event
    # (content is retained) but drop the hard RESTRICT so an unused school can
    # be deleted; the link is cleared instead of blocking the delete.
    op.drop_constraint(
        "fk_audit_events_school_id_schools", "audit_events", type_="foreignkey"
    )
    op.create_foreign_key(
        "fk_audit_events_school_id_schools",
        "audit_events",
        "schools",
        ["school_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_audit_events_school_id_schools", "audit_events", type_="foreignkey"
    )
    op.create_foreign_key(
        "fk_audit_events_school_id_schools",
        "audit_events",
        "schools",
        ["school_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.drop_column("schools", "updated_at")
    op.drop_column("schools", "longitude")
    op.drop_column("schools", "latitude")
    op.drop_column("schools", "description")
    op.drop_column("schools", "phone")
    op.drop_column("schools", "city")
    op.drop_column("schools", "postal_code")
    op.drop_column("schools", "street")
