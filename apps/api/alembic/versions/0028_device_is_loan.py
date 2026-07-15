"""Device loaner flag

Adds ``devices.is_loan`` (BOOL, default false) so a device assigned to a person
can be marked as a loaner (Leihgerät) rather than their fixed device.

Revision ID: 0028_device_is_loan
Revises: 0027_ad_group_catalog
Create Date: 2026-07-15
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0028_device_is_loan"
down_revision: str | Sequence[str] | None = "0027_ad_group_catalog"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "devices",
        sa.Column("is_loan", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column("devices", "is_loan")
