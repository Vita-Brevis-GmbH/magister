"""Passwort-Import: Import-Art "passwords", verschlüsselter Zwischenstand

Revision ID: 0048_password_import
Revises: 0047_zielgruppen
Create Date: 2026-10-19

Bestehende Konten (Übernahme einer alten Anlage) behalten ihre bekannten
Passwörter: der Import setzt sie im AD und legt sie im Tresor ab, damit die
Klassen-Passwortlisten der Unterstufe wieder funktionieren.

Zwischen Hochladen und Übernehmen liegt das Passwort in
``import_staged_rows.secret_enc`` — mit dem Kundenschlüssel verschlüsselt
(pgcrypto), nie in ``raw_data`` (das zeigt die Oberfläche an). Nach dem
Übernehmen oder Abbrechen wird die Spalte geleert.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0048_password_import"
down_revision: str | Sequence[str] | None = "0047_zielgruppen"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_OLD = (
    "kind IN ('classes', 'class_memberships', 'class_teachers', "
    "'students', 'teachers', 'company_users')"
)
_NEW = (
    "kind IN ('classes', 'class_memberships', 'class_teachers', "
    "'students', 'teachers', 'company_users', 'passwords')"
)


def upgrade() -> None:
    op.drop_constraint("ck_import_jobs_kind", "import_jobs", type_="check")
    op.create_check_constraint("ck_import_jobs_kind", "import_jobs", _NEW)
    op.add_column("import_staged_rows", sa.Column("secret_enc", sa.LargeBinary(), nullable=True))


def downgrade() -> None:
    op.drop_column("import_staged_rows", "secret_enc")
    op.execute("DELETE FROM import_jobs WHERE kind = 'passwords'")
    op.drop_constraint("ck_import_jobs_kind", "import_jobs", type_="check")
    op.create_check_constraint("ck_import_jobs_kind", "import_jobs", _OLD)
