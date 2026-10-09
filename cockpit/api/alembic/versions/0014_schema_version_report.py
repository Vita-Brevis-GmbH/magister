"""Wann die Datenebene den Schemastand gemeldet hat (ADR-0021 D2).

`schema_version` gab es schon. Was fehlte, ist der Unterschied zwischen einer
**Erwartung** (gesetzt beim Aktivieren, aus `COCKPIT_EXPECTED_SCHEMA_VERSION`)
und einer **Messung** (gemeldet von der Stelle, die migriert hat). Ohne
Zeitstempel sieht beides gleich aus, und die Versions-Schranke fährt nach
dieser Spalte.

Revision ID: 0014_schema_version_report
Revises: 0013_console_operators
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0014_schema_version_report"
down_revision = "0013_console_operators"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "tenants",
        sa.Column("schema_version_reported_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("tenants", "schema_version_reported_at")
