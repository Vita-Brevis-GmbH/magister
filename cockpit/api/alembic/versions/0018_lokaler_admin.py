"""Parameter für Wartungsaufträge (lokales Admin-Konto, ADR-0024 Nachtrag).

Revision ID: 0018_lokaler_admin
Revises: 0017_betrieb_aus_der_konsole
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0018_lokaler_admin"
down_revision = "0017_betrieb_aus_der_konsole"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "tenant_maintenance_requests",
        sa.Column("params", postgresql.JSONB(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("tenant_maintenance_requests", "params")
