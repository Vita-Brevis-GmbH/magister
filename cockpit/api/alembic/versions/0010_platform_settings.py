"""Systemeinstellungen und Rechte-Matrix als Soll-Zustand (ADR-0017)

Revision ID: 0010_platform_settings
Revises: 0009_monthly_backups
Create Date: 2026-09-10

Zwei Tabellen: die Vorgaben für alle Kunden (`platform_settings`, genau eine
Zeile) und die Abweichungen je Kunde (`tenant_settings`).

**JSONB und nicht vierzig Spalten.** Die Felder gehören der Datenebene
(`app_settings`); jedes neue Feld dort wäre sonst eine Migration hier. Was
erlaubt ist, prüft der Dienst gegen eine ausdrückliche Allowlist
(`services/settings.py::POLICY_KEYS`) — nicht das Schema. Der Preis: die
Datenbank kann einen Tippfehler im Schlüsselnamen nicht abweisen. Der Gewinn:
die Konsole muss nicht bei jedem neuen Schalter der Datenebene nachgezogen
werden, und die Prüfung sitzt an einer Stelle statt in einer Spaltenliste.

**Keine Geheimnisse** (ADR-0017 D2). Kein AD-Bind-Passwort, kein
OIDC-Client-Secret, kein privater Webserver-Schlüssel. Die Konsole wäre der
eine Ort, an dem die Geheimnisse aller Kunden zusammenkämen — deshalb kommen
sie dort nicht hin.

`ON DELETE CASCADE` auf `tenant_settings`: verschwindet ein Kunde beim
Offboarding, verschwinden seine Abweichungen mit. Eine verwaiste Zeile mit den
Einstellungen eines gelöschten Kunden wäre Restdaten, die niemand aufräumt.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0010_platform_settings"
down_revision: str | None = "0009_monthly_backups"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "platform_settings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "defaults",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="{}",
        ),
        sa.Column(
            "rbac",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="{}",
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("updated_by", sa.String(length=320), nullable=True),
        # Die Zeile ist ein Singleton. Ohne diese Schranke erzeugt ein
        # fehlerhafter Aufruf eine zweite Zeile, und danach ist die Frage
        # „welche gilt?" eine Ausfallursache.
        sa.CheckConstraint("id = 1", name="ck_platform_settings_singleton"),
    )
    op.create_table(
        "tenant_settings",
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "overrides",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="{}",
        ),
        # Nullable, und der Unterschied zählt: `NULL` heisst „keine eigene
        # Matrix, die globale gilt", `{}` heisst „eigene Matrix, und die ist
        # leer". Letzteres würde eine Installation entrechten.
        sa.Column("rbac", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("updated_by", sa.String(length=320), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("tenant_settings")
    op.drop_table("platform_settings")
