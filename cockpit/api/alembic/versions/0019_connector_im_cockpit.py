"""Connector-Einstellungen je Kunde im Cockpit (ADR-0014 Nachtrag).

Revision ID: 0019_connector_im_cockpit
Revises: 0018_lokaler_admin
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0019_connector_im_cockpit"
down_revision = "0018_lokaler_admin"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "tenant_connector_settings",
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("allowed_ous", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("protected_groups", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("updated_by", sa.String(320), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("tenant_connector_settings")
