"""Monatskopien der Sicherungen (Entscheid E15)

Revision ID: 0009_monthly_backups
Revises: 0008_agent_renewal
Create Date: 2026-09-09

Zehn Tage Aufbewahrung (E14) decken zwei Fälle nicht ab, und beide sind bei
Schulen realistisch: ein Fehler, der erst am Quartalsende auffällt, und ein
Verschlüsselungstrojaner, der Wochen im Netz sass, bevor er zuschlug. Deshalb
zwölf Monatskopien.

``monthly_keep`` ist eine **Anzahl** und keine Frist in Tagen: „die letzten
zwölf" hat keine Kanten am 31., braucht keine Monatsarithmetik und trifft die
Zusage genauer als 365 Tage.

Eingeschaltet als Vorgabe, weil E15 mit „ja machen" entschieden wurde. Wer es
nicht will, setzt es je Kunde ab — es ist eine Vertragsfrage.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0009_monthly_backups"
down_revision: str | None = "0008_agent_renewal"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Neuer Wert im Enum. In Postgres geht das nur mit ALTER TYPE, und ALTER
    # TYPE ... ADD VALUE lässt sich in älteren Fassungen nicht in derselben
    # Transaktion benutzen. Seit Postgres 12 ist es erlaubt, solange der neue
    # Wert nicht in derselben Transaktion *verwendet* wird — und das tut diese
    # Migration nicht.
    op.execute(sa.text("ALTER TYPE backup_kind ADD VALUE IF NOT EXISTS 'monthly'"))

    op.add_column(
        "tenant_backup_policy",
        sa.Column("monthly_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.add_column(
        "tenant_backup_policy",
        sa.Column("monthly_keep", sa.Integer(), nullable=False, server_default="12"),
    )


def downgrade() -> None:
    op.drop_column("tenant_backup_policy", "monthly_keep")
    op.drop_column("tenant_backup_policy", "monthly_enabled")
    # Der Enum-Wert bleibt. Ihn zu entfernen hiesse, den Typ neu zu bauen und
    # jede Spalte umzuhängen, die ihn benutzt — und Zeilen mit kind='monthly'
    # müssten vorher umgeschrieben werden. Ein zurückgerollter Stand mit einem
    # zusätzlichen Enum-Wert ist harmlos; ein Rollback, der Sicherungszeilen
    # verändert, ist es nicht.
