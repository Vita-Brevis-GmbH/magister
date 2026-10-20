"""Zielgruppen: "im Tresor ablegen" nur bei festem Passwort

Revision ID: 0050_tresor_fest
Revises: 0049_zielgruppe_ou
Create Date: 2026-10-20

Ein Passwort kommt nur noch in den Tresor, wenn es so bleibt: keine
erzwungene Änderung bei der ersten Anmeldung, der Benutzer kann es nicht
ändern, und es läuft nie ab. Zielgruppen, die den Tresor ohne diese drei
vorsahen, verlieren den Schalter — die Oberfläche bietet ihn dort nicht
mehr an.

Bereits abgelegte Passwörter einzelner Konten bleiben unangetastet: sie
löschen hiesse, Klassenlisten ohne Rückfrage zu leeren. Sie fallen beim
nächsten Reset oder bei der nächsten Änderung der Konto-Einstellungen weg.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0050_tresor_fest"
down_revision: str | Sequence[str] | None = "0049_zielgruppe_ou"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "UPDATE group_templates SET store_password = false "
        "WHERE store_password AND NOT "
        "(cannot_change_password AND password_never_expires AND NOT force_change)"
    )


def downgrade() -> None:
    # Nichts zurückzunehmen: welche Zielgruppe den Schalter vorher hatte,
    # ist nicht mehr bekannt, und "aus" ist der sichere Stand.
    pass
