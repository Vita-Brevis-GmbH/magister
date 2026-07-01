"""class details free-text field

Adds a nullable ``details`` text column to ``classes`` so Schulleitung/Admin
can annotate a class (room, focus, notes) and edit it alongside name/kuerzel.

Revision ID: 0012_class_details
Revises: 0011_audit_key_id
Create Date: 2026-06-30
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0012_class_details"
down_revision: str | Sequence[str] | None = "0011_audit_key_id"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("classes", sa.Column("details", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("classes", "details")
