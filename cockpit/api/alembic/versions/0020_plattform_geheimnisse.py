"""Plattform-Geheimnisse: versiegelt für alle Kunden (Standard-Mailversand).

Revision ID: 0020_plattform_geheimnisse
Revises: 0019_connector_im_cockpit
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0020_plattform_geheimnisse"
down_revision = "0019_connector_im_cockpit"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "platform_sealed_secrets",
        sa.Column("name", sa.String(64), primary_key=True),
        sa.Column("ciphertext", sa.Text(), nullable=False),
        sa.Column("key_id", sa.String(64), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("updated_by", sa.String(320), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("platform_sealed_secrets")
