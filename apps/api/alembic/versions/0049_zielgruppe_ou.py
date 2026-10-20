"""Zielgruppe: optionale Ziel-OU bei freier Kontoart

Revision ID: 0049_zielgruppe_ou
Revises: 0048_kennwort_import
Create Date: 2026-10-20

Eine Zielgruppe ohne feste Kontoart ("custom" oder leer) — etwa "Gäste",
"Externe Lehrpersonen" oder bei Firmen eine Abteilung — legt neue Konten in
``group_templates.ad_ou`` ab. Leer = wie bisher die OU des Standorts für die
bei der Anlage gewählte Kontoart.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0049_zielgruppe_ou"
down_revision: str | Sequence[str] | None = "0048_kennwort_import"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("group_templates", sa.Column("ad_ou", sa.String(512), nullable=True))


def downgrade() -> None:
    op.drop_column("group_templates", "ad_ou")
