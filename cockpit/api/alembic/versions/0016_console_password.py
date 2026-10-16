"""Passwort als erster Faktor der Konsole (ADR-0023).

Vier Spalten und zwei gelockerte Pflichten:

* `console_operators.password_hash` — argon2id, `NULL` heisst „kein Passwort".
* `console_operators.spki_fingerprint` wird **nullable**. Wer sich mit
  Passwort anmeldet, hat kein Zertifikat; die Eindeutigkeit bleibt (mehrere
  `NULL` sind in einem UNIQUE-Index in Postgres kein Konflikt).
* `console_sessions.spki_fingerprint` ebenso.
* `console_sessions.pending_totp` — der Zwischenstand zwischen Passwort und
  zweitem Faktor (ADR-0023 D2).

Bestehende Operatoren behalten Zertifikat und Fingerprint und melden sich
weiter so an. Ein Passwort bekommen sie über `add_operator --set-password`;
die Migration erfindet keines.

Revision ID: 0016_console_password
Revises: 0015_tenant_limits
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0016_console_password"
down_revision = "0015_tenant_limits"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "console_operators", sa.Column("password_hash", sa.String(length=255), nullable=True)
    )
    op.add_column(
        "console_operators",
        sa.Column("password_set_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "console_operators",
        sa.Column("login_failed_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.alter_column(
        "console_operators", "spki_fingerprint", existing_type=sa.String(length=64), nullable=True
    )
    op.alter_column(
        "console_sessions", "spki_fingerprint", existing_type=sa.String(length=64), nullable=True
    )
    op.add_column(
        "console_sessions",
        sa.Column("pending_totp", sa.Boolean(), nullable=False, server_default="false"),
    )


def downgrade() -> None:
    # Zurück geht es nur, solange jeder Operator ein Zertifikat hat. Sonst
    # stünde am Ende eine Zeile ohne Fingerprint in einer NOT-NULL-Spalte —
    # die Migration bricht dann ab, und das ist die richtige Auskunft.
    op.drop_column("console_sessions", "pending_totp")
    op.alter_column(
        "console_sessions", "spki_fingerprint", existing_type=sa.String(length=64), nullable=False
    )
    op.alter_column(
        "console_operators", "spki_fingerprint", existing_type=sa.String(length=64), nullable=False
    )
    op.drop_column("console_operators", "login_failed_count")
    op.drop_column("console_operators", "password_set_at")
    op.drop_column("console_operators", "password_hash")
