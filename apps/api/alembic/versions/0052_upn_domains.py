"""Zusätzliche UPN-Domains für die Auswahl

Revision ID: 0052_upn_domains
Revises: 0051_ablauf_erinnerung
Create Date: 2026-10-22

Mail- und UPN-Domains pflegt der Kunde in den Systemeinstellungen (auch
gehostet). Neben den Mail-Domains eine eigene Liste für UPN-Suffixe ohne
Mailzustellung.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0052_upn_domains"
down_revision: str | Sequence[str] | None = "0051_ablauf_erinnerung"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "app_settings",
        sa.Column(
            "upn_domains",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )


def downgrade() -> None:
    op.drop_column("app_settings", "upn_domains")
