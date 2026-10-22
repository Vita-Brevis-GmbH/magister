"""Globale Vorlagen der Plattform (ADR-0018)

Revision ID: 0011_platform_templates
Revises: 0010_platform_settings
Create Date: 2026-09-10

Zwei Tabellen: die Vorlage selbst und, bei `audience = selection`, die
gewählten Kunden.

**`tenant_profile` wird nicht neu angelegt.** Den Postgres-Typ gibt es seit
`0004_tenants`. Ein zweites `CREATE TYPE` scheiterte an „type already exists" —
deshalb `postgresql.ENUM(..., create_type=False)` für dieses Feld und ein
frisches `CREATE TYPE` nur für `template_audience`.

**Die Fassungsnummer beginnt bei 1 und ist `>= 1` erzwungen.** Sie wird beim
Kunden gegen eine quittierte Fassung verglichen (ADR-0018 D4); eine 0 oder ein
`NULL` würde „noch nie quittiert" und „Fassung null" ununterscheidbar machen.

**Der CheckConstraint auf das Profil** hält fest, was der Dienst ebenfalls
prüft: ein Profil gehört zu `audience = profile` und nur dorthin. In der
Datenbank, damit es auch für ein `psql` gilt — eine Zeile mit einem Profil,
das niemand anwendet, wäre eine, die man beim Lesen für wirksam hält.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0011_platform_templates"
down_revision: str | None = "0010_platform_settings"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

audience = postgresql.ENUM(
    "all", "profile", "selection", name="template_audience", create_type=False
)
profile = postgresql.ENUM("school", "company", "neutral", name="tenant_profile", create_type=False)


def upgrade() -> None:
    audience.create(op.get_bind(), checkfirst=True)
    op.create_table(
        "platform_templates",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("key", sa.String(length=64), nullable=False),
        sa.Column("language", sa.String(length=8), nullable=False),
        sa.Column("subject", sa.String(length=512), nullable=True),
        sa.Column("body_html", sa.Text(), nullable=False, server_default=""),
        sa.Column("may_override", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("audience", audience, nullable=False, server_default="all"),
        sa.Column("audience_profile", profile, nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("updated_by", sa.String(length=320), nullable=True),
        sa.CheckConstraint(
            "(audience = 'profile') = (audience_profile IS NOT NULL)",
            name="ck_platform_templates_profile",
        ),
        sa.CheckConstraint("version >= 1", name="ck_platform_templates_version"),
    )
    op.create_index(
        "ix_platform_templates_key_lang",
        "platform_templates",
        ["key", "language"],
        unique=True,
    )
    op.create_table(
        "platform_template_tenants",
        sa.Column(
            "platform_template_id",
            sa.Integer(),
            sa.ForeignKey("platform_templates.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        # `ON DELETE CASCADE` auch hier: ein gekündigter Kunde verschwindet aus
        # der Auswahl, statt als Id einer nicht mehr existierenden Zeile
        # liegenzubleiben.
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            primary_key=True,
        ),
    )
    op.create_index(
        "ix_platform_template_tenants_tenant_id",
        "platform_template_tenants",
        ["tenant_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_platform_template_tenants_tenant_id", table_name="platform_template_tenants")
    op.drop_table("platform_template_tenants")
    op.drop_index("ix_platform_templates_key_lang", table_name="platform_templates")
    op.drop_table("platform_templates")
    # Nur der hier angelegte Typ wird entfernt. `tenant_profile` gehört
    # `0004_tenants` und bleibt.
    audience.drop(op.get_bind(), checkfirst=True)
