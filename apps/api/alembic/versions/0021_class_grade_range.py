"""classes: optional upper grade for multi-grade classes (Mehrjahrgang/Basisstufe)

Adds ``jahrgangsstufe_bis`` — the upper grade of a class that spans several
grades. NULL = single-grade class (== jahrgangsstufe). The existing
``jahrgangsstufe`` stays the lower/primary grade and keeps driving Zyklus/OU
routing, sorting and promotion. Kindergarten years are encoded below grade 1
(-1 = 1. Kindergarten, 0 = 2. Kindergarten); no DB constraint change needed as
the column was always a plain integer.

Revision ID: 0021_class_grade_range
Revises: 0020_devices
Create Date: 2026-07-13
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0021_class_grade_range"
down_revision: str | Sequence[str] | None = "0020_devices"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("classes", sa.Column("jahrgangsstufe_bis", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("classes", "jahrgangsstufe_bis")
