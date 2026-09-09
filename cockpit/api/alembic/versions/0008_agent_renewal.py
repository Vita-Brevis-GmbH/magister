"""connector_agents: vorheriger SPKI-Fingerprint für die Erneuerung (ADR-0014)

Revision ID: 0008_agent_renewal
Revises: 0007_offboarding
Create Date: 2026-09-09

Zwei Spalten, die eine einzige Aussperrung verhindern.

Das Agentenzertifikat gilt 90 Tage. Bei der Erneuerung schreibt die Plattform
den neuen Fingerprint in die Zeile — geht die Antwort auf dem Rückweg verloren
(abgebrochene Verbindung, Proxy-Zeitüberschreitung, Neustart des Agenten in
genau diesem Moment), klopft der Agent weiter mit dem alten Schlüssel an, auf
eine Zeile, die ihn nicht mehr kennt. Er wäre ausgesperrt, und zwar endgültig:
ein neues Einmal-Token kann nur ein Mensch ausstellen, und beim Kunden sitzt
niemand daneben.

Mit ``previous_spki_sha256`` gelten beide Fingerprints für ein Zeitfenster
(``connector.ROTATION_GRACE``, sieben Tage). ``spki_rotated_at`` begrenzt es —
ein Schlüssel, der ewig zusätzlich gilt, ist ein zweiter Schlüssel und kein
Übergang.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0008_agent_renewal"
down_revision: str | None = "0007_offboarding"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "connector_agents", sa.Column("previous_spki_sha256", sa.String(64), nullable=True)
    )
    op.add_column(
        "connector_agents",
        sa.Column("spki_rotated_at", sa.DateTime(timezone=True), nullable=True),
    )
    # Index, weil die Authentisierung bei JEDER Anfrage danach sucht, wenn der
    # aktuelle Fingerprint nicht passt. Ohne ihn wäre der Fehlschlag-Pfad ein
    # Full Table Scan — und genau der wird bei einem Angriff mit erfundenen
    # Fingerprints am häufigsten genommen.
    #
    # Kein UNIQUE: nach Ablauf des Übergangsfensters bleiben die Werte stehen,
    # bis sich der Agent das nächste Mal meldet, und zwei Agenten könnten
    # theoretisch denselben alten Wert tragen (praktisch nicht, aber ein
    # UNIQUE, das man nicht braucht, ist eine Fehlerquelle beim Aufräumen).
    op.create_index(
        "ix_connector_agents_previous_spki",
        "connector_agents",
        ["previous_spki_sha256"],
    )


def downgrade() -> None:
    op.drop_index("ix_connector_agents_previous_spki", table_name="connector_agents")
    op.drop_column("connector_agents", "spki_rotated_at")
    op.drop_column("connector_agents", "previous_spki_sha256")
