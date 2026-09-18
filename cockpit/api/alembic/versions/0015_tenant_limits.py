"""Lastgrenzen an der Mandantenrolle (ADR-0021 D3).

Drei Spalten mit Vorgabewerten. Die Wahrheit ist die Rolle in Postgres; diese
Spalten sind, was die Konsole dorthin geschrieben hat — deshalb `NOT NULL` mit
Vorgabe und nicht nullable: ein leerer Wert wäre „keine Grenze", und das ist
genau der Zustand, den ADR-0021 D3 beendet.

Bestehende Kunden bekommen die Vorgabewerte in die Spalten, aber **nicht** an
die Rolle: das tut erst ein Aufruf von `apply_limits` (oder die nächste
Bereitstellung). Eine Migration, die in einen anderen Cluster hineingreift,
wäre eine Migration mit zwei Datenbanken — siehe Runbook.

Revision ID: 0015_tenant_limits
Revises: 0014_schema_version_report
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0015_tenant_limits"
down_revision = "0014_schema_version_report"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "tenants",
        sa.Column(
            "statement_timeout_ms",
            sa.Integer(),
            nullable=False,
            server_default="30000",
        ),
    )
    op.add_column(
        "tenants",
        sa.Column(
            "idle_in_transaction_ms",
            sa.Integer(),
            nullable=False,
            server_default="60000",
        ),
    )
    op.add_column(
        "tenants",
        sa.Column("connection_limit", sa.Integer(), nullable=False, server_default="40"),
    )


def downgrade() -> None:
    op.drop_column("tenants", "connection_limit")
    op.drop_column("tenants", "idle_in_transaction_ms")
    op.drop_column("tenants", "statement_timeout_ms")
