"""Operatoren der Konsole und ihre Sitzungen (ADR-0020)

Revision ID: 0013_console_operators
Revises: 0012_operator_access
Create Date: 2026-09-11

`pgcrypto` wird hier eingeschaltet. Die Konsolen-Datenbank hatte bisher keine
verschlüsselte Spalte — der API-Key eines Agenten liegt als argon2id-Hash,
und ein Hash braucht keine Erweiterung. Ein TOTP-Geheimnis muss lesbar
zurückkommen, also braucht es Verschlüsselung, und dafür dieselbe Mechanik wie
in der Datenebene (`pgp_sym_encrypt`) statt einer zweiten.

`CREATE EXTENSION` verlangt Superuser-Rechte. In der Compose-Datei ist der
Besitzer der Konsolen-Datenbank (`POSTGRES_USER: cockpit`) einer — bei einer
Installation auf einen bestehenden Cluster muss die Erweiterung vorher da sein,
sonst bricht diese Migration ab. Das ist gewollt: ein stiller Start ohne
Verschlüsselung wäre schlimmer.

Der Fingerprint ist eindeutig (ADR-0020 D1): zwei Operatoren können nicht
dasselbe Schlüsselpaar benutzen.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0013_console_operators"
down_revision: str | None = "0012_operator_access"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")
    op.create_table(
        "console_operators",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("upn", sa.String(length=320), nullable=False, unique=True),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("spki_fingerprint", sa.String(length=64), nullable=False, unique=True),
        sa.Column("totp_secret_enc", sa.LargeBinary(), nullable=True),
        sa.Column("totp_confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("totp_last_step", sa.BigInteger(), nullable=True),
        sa.Column(
            "recovery_codes",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="[]",
        ),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("mfa_failed_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_table(
        "console_sessions",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column(
            "operator_id",
            sa.Integer(),
            sa.ForeignKey("console_operators.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "last_seen_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("ip", sa.String(length=64), nullable=True),
        sa.Column("user_agent", sa.String(length=512), nullable=True),
        sa.Column("spki_fingerprint", sa.String(length=64), nullable=False),
    )
    op.create_index("ix_console_sessions_operator", "console_sessions", ["operator_id"])


def downgrade() -> None:
    op.drop_index("ix_console_sessions_operator", table_name="console_sessions")
    op.drop_table("console_sessions")
    op.drop_table("console_operators")
    # `pgcrypto` bleibt: andere Dinge könnten sie inzwischen benutzen, und eine
    # Erweiterung zu entfernen ist kein Rückbau dieser Migration.
