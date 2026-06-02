"""add latest_available_version + update_requests

Revision ID: 0002_update_requests
Revises: 0001_initial
Create Date: 2026-06-02

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002_update_requests"
down_revision: str | None = "0001_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "instances",
        sa.Column("latest_available_version", sa.String(64), nullable=True),
    )
    op.create_table(
        "update_requests",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "instance_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("instances.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("target_version", sa.String(64), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "pending",
                "in_progress",
                "completed",
                "failed",
                "cancelled",
                name="update_request_status",
            ),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("note", sa.String(500), nullable=True),
        sa.Column("requested_by", sa.String(200), nullable=True),
        sa.Column(
            "requested_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.String(1000), nullable=True),
    )
    op.create_index("ix_update_requests_instance_id", "update_requests", ["instance_id"])


def downgrade() -> None:
    op.drop_index("ix_update_requests_instance_id", table_name="update_requests")
    op.drop_table("update_requests")
    op.execute("DROP TYPE update_request_status")
    op.drop_column("instances", "latest_available_version")
