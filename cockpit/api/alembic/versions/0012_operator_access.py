"""Ausgestellte Operator-Assertions (ADR-0019)

Revision ID: 0012_operator_access
Revises: 0011_platform_templates
Create Date: 2026-09-11

Was die Konsole ausgestellt hat, mit Grund und Ablauf. Ob ein Zugriff
tatsächlich stattgefunden hat, steht **nicht** hier, sondern im Kundenschema
(ADR-0019 D4) — die Konsole hat dorthin keinen Zugang, und das ist der Grund,
aus dem ein Einbruch in die Konsole nicht auch einer in jeden Kunden ist.

Der Primärschlüssel ist der `jti` der Assertion und kein eigener Zähler: damit
sind die Zeile hier und die Zeile beim Kunden über denselben Wert verbunden,
ohne dass jemand sie zuordnen muss.

`reason` ist `TEXT` und nicht `VARCHAR(n)`: eine Begründung, die bei 200
Zeichen abgeschnitten wird, ist genau dann abgeschnitten, wenn sie ausführlich
war.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0012_operator_access"
down_revision: str | None = "0011_platform_templates"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "operator_access_grants",
        sa.Column("jti", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("operator", sa.String(length=320), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("ticket", sa.String(length=64), nullable=True),
        sa.Column(
            "issued_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_operator_access_grants_tenant",
        "operator_access_grants",
        ["tenant_id", "issued_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_operator_access_grants_tenant", table_name="operator_access_grants")
    op.drop_table("operator_access_grants")
