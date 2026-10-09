"""Vom Betreiber gelieferte Vorlagen und die Quittung dazu (ADR-0018)

Revision ID: 0045_platform_document_templates
Revises: 0044_local_admin_totp
Create Date: 2026-09-10

Zwei Änderungen, die zusammengehören:

- ``platform_document_templates`` — was der Betreiber liefert. Eine **eigene**
  Tabelle neben ``document_templates`` (ADR-0018 D2): der Abgleich schreibt
  ausschliesslich hierhin, und damit ist "der eigene Text des Kunden bleibt
  unangetastet" keine Sorgfalt, sondern Bauart.
- ``document_templates.platform_version_ack`` — welche Plattformfassung der
  Kunde zur Kenntnis genommen hat. ``NULL`` heisst "noch keine", und das ist
  der Anfangszustand für jede bestehende Zeile: der Hinweis "neue globale
  Fassung verfügbar" erscheint beim ersten Mal, und genau so ist er gemeint.

Kein ``school_id`` an der neuen Tabelle. Eine Plattformvorlage gilt für den
ganzen Mandanten; der Betreiber kennt die Standorte seiner Kunden nicht und
soll sie nicht kennen müssen. Welcher Standort einen Brief bekommt, entscheidet
weiterhin die Auflösung im Renderer (ADR-0018 D3).

Auf einer Einzelinstallation ohne Konsole bleibt die Tabelle leer. Sie kostet
dort nichts und erspart eine zweite Migrationslinie.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0045_platform_document_templates"
down_revision: str | None = "0044_local_admin_totp"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "platform_document_templates",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("key", sa.String(length=64), nullable=False),
        sa.Column("language", sa.String(length=8), nullable=False),
        sa.Column("subject", sa.String(length=512), nullable=True),
        sa.Column("body_html", sa.Text(), nullable=False, server_default=""),
        sa.Column("may_override", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column(
            "delivered_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        # Die Fassungsnummer wird gegen eine quittierte Fassung verglichen. Eine
        # 0 oder ein NULL würde "noch nie quittiert" und "Fassung null"
        # ununterscheidbar machen.
        sa.CheckConstraint("version >= 1", name="ck_platform_document_templates_version"),
    )
    op.create_index(
        "ix_platform_document_templates_key_lang",
        "platform_document_templates",
        ["key", "language"],
        unique=True,
    )
    op.add_column(
        "document_templates",
        sa.Column("platform_version_ack", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("document_templates", "platform_version_ack")
    op.drop_index(
        "ix_platform_document_templates_key_lang", table_name="platform_document_templates"
    )
    op.drop_table("platform_document_templates")
