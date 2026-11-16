"""Rollen nur aus dem Cockpit: Merker im Kundenschema (ADR-0027)

Revision ID: 0054_rollen_nur_cockpit
Revises: 0053_anmeldekonten
Create Date: 2026-11-16

``app_settings.roles_from_cockpit`` hält fest, ob das Cockpit die Rollen dieses
Kunden führt (Soll-Zustand ``role_assignments`` ≠ ``null``). Der Abgleich setzt
ihn, die API liest ihn bei jeder Rollen- und Kontoänderung: der Soll-Zustand
selbst liegt nur im Speicher des Abgleichs, und nach einem Neustart soll die
Sperre nicht bis zum ersten Lauf offen stehen.

Vorgabe ``false``: bis zum ersten Abgleich nach dem Update gilt, was vorher
galt.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0054_rollen_nur_cockpit"
down_revision: str | Sequence[str] | None = "0053_anmeldekonten"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "app_settings",
        sa.Column("roles_from_cockpit", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column("app_settings", "roles_from_cockpit")
