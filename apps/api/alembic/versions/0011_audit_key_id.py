"""audit_events.key_id

Revision ID: 0011_audit_key_id
Revises: 0010_ad_sync_state
Create Date: 2026-06-02

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0011_audit_key_id"
down_revision: str | None = "0010_ad_sync_state"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "audit_events",
        sa.Column("key_id", sa.String(32), nullable=False, server_default="v1"),
    )


def downgrade() -> None:
    op.drop_column("audit_events", "key_id")
