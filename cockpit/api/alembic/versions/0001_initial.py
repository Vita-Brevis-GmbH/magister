"""initial

Revision ID: 0001_initial
Revises:
Create Date: 2026-06-02

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001_initial"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "instances",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("slug", sa.String(64), nullable=False, unique=True),
        sa.Column("display_name", sa.String(200), nullable=False),
        sa.Column("base_url", sa.String(500), nullable=False),
        sa.Column(
            "channel",
            sa.Enum("stable", "latest", name="instance_channel"),
            nullable=False,
            server_default="stable",
        ),
        sa.Column("deployed_version", sa.String(64), nullable=True),
        sa.Column("last_health_status", sa.String(32), nullable=True),
        sa.Column("last_health_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.String(1000), nullable=True),
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
    )
    op.create_index("ix_instances_slug", "instances", ["slug"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_instances_slug", table_name="instances")
    op.drop_table("instances")
    op.execute("DROP TYPE instance_channel")
