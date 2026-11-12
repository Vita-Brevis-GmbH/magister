"""Eingelöste Operator-Zugriffe und die Sitzung dazu (ADR-0019)

Revision ID: 0046_operator_access
Revises: 0045_platform_document_templates
Create Date: 2026-09-11

``operator_accesses`` ist Einlöseprotokoll **und** Zugriffsliste in einer
Tabelle (ADR-0019 D4). Der Primärschlüssel auf ``jti`` weist die zweite
Einlösung derselben Assertion ab — durch Postgres und nicht durch eine
Prüfung im Code, die bei zwei gleichzeitigen Anfragen beide durchlässt.

Deshalb wird hier auch **nichts aufgeräumt**: ein separater Nonce-Speicher mit
Verfall würde alte Einträge löschen, und damit wäre eine alte Assertion
irgendwann wieder einlösbar. Ausserdem soll der Kunde die Historie sehen.

``session_ref`` hält nur die ersten Zeichen der Session-Id. Der vollständige
Wert ist das Cookie und damit ein Zugangsmittel; ihn in einer Tabelle zu
führen, die nie aufgeräumt wird, wäre ein Passwortspeicher.

An ``sessions`` kommen zwei Spalten: wer zusieht und mit welchem
Einlöseschein. Bestehende Zeilen bekommen ``NULL`` — sie sind keine
Operator-Sitzungen, und ``auth_kind`` sagt das schon.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0046_operator_access"
down_revision: str | None = "0045_platform_document_templates"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "operator_accesses",
        sa.Column("jti", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("operator_upn", sa.String(length=320), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("ticket", sa.String(length=64), nullable=True),
        sa.Column("session_ref", sa.String(length=16), nullable=False),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ip", sa.String(length=64), nullable=True),
    )
    op.create_index("ix_operator_accesses_started", "operator_accesses", ["started_at"])
    op.add_column("sessions", sa.Column("operator_upn", sa.String(length=320), nullable=True))
    op.add_column(
        "sessions", sa.Column("operator_jti", postgresql.UUID(as_uuid=True), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("sessions", "operator_jti")
    op.drop_column("sessions", "operator_upn")
    op.drop_index("ix_operator_accesses_started", table_name="operator_accesses")
    op.drop_table("operator_accesses")
