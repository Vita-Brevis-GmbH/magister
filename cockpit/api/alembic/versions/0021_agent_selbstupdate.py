"""Selbstupdate des Connector-Agenten: Schalter, Wartungsfenster, letzte Meldung.

Revision ID: 0021_agent_selbstupdate
Revises: 0020_plattform_geheimnisse
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0021_agent_selbstupdate"
down_revision = "0020_plattform_geheimnisse"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "tenant_connector_settings",
        sa.Column("auto_update", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.add_column(
        "tenant_connector_settings",
        sa.Column("update_window", sa.String(11), nullable=False, server_default="02:00-04:00"),
    )
    op.add_column("connector_agents", sa.Column("update_status", sa.String(500), nullable=True))
    op.add_column(
        "connector_agents",
        sa.Column("update_status_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("connector_agents", "update_status_at")
    op.drop_column("connector_agents", "update_status")
    op.drop_column("tenant_connector_settings", "update_window")
    op.drop_column("tenant_connector_settings", "auto_update")
