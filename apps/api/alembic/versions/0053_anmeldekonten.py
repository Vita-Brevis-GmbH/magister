"""Anmeldekonten aus dem Keycloak-Realm (ADR-0025)

Revision ID: 0053_anmeldekonten
Revises: 0052_upn_domains
Create Date: 2026-11-13

Die Anmeldung hängt nicht mehr am AD-Abgleich: wer sich am Keycloak-Realm des
Kunden anmeldet, bekommt hier ein Konto. Identität ist ``issuer`` + ``subject``
(beide leer, solange ein vorab angelegtes Konto noch nie angemeldet war),
``username`` ist eindeutig und klein geschrieben. ``principal_guid`` ist der
Schlüssel für Rollen und Sitzungen.

Keine Datenübernahme: bestehende Benutzer bekommen ihr Konto bei der ersten
Anmeldung, und über ``upn == username`` dieselbe GUID wie bisher.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0053_anmeldekonten"
down_revision: str | Sequence[str] | None = "0052_upn_domains"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "login_accounts",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("issuer", sa.String(length=512), nullable=True),
        sa.Column("subject", sa.String(length=255), nullable=True),
        sa.Column("username", sa.String(length=255), nullable=False),
        sa.Column("display_name", sa.String(length=200), nullable=True),
        sa.Column("email", sa.String(length=320), nullable=True),
        sa.Column("principal_guid", sa.String(length=36), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_login_accounts"),
        sa.UniqueConstraint("username", name="uq_login_accounts_username"),
        sa.UniqueConstraint("principal_guid", name="uq_login_accounts_principal_guid"),
        sa.UniqueConstraint("issuer", "subject", name="uq_login_accounts_issuer_subject"),
        # Kurze Namen: die Namenskonvention (`ck_<tabelle>_<name>`) setzt den
        # Tabellennamen davor — so heissen sie wie im Modell.
        sa.CheckConstraint("username = lower(username)", name="username_lower"),
        sa.CheckConstraint("(issuer IS NULL) = (subject IS NULL)", name="binding_complete"),
    )


def downgrade() -> None:
    op.drop_table("login_accounts")
