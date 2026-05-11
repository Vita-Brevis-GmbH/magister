"""app_settings: singleton row for OIDC + AD config

Revision ID: 0006_app_settings
Revises: 0005_local_admin
Create Date: 2026-05-08
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision: str = "0006_app_settings"
down_revision: str | Sequence[str] | None = "0005_local_admin"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "app_settings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default=sa.text("1")),
        # OIDC
        sa.Column("oidc_issuer", sa.String(length=512), nullable=True),
        sa.Column("oidc_client_id", sa.String(length=255), nullable=True),
        sa.Column("oidc_client_secret_enc", sa.LargeBinary(), nullable=True),
        sa.Column("oidc_redirect_uri", sa.String(length=512), nullable=True),
        sa.Column(
            "oidc_scopes",
            JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "bootstrap_admins",
            JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        # AD
        sa.Column(
            "ad_dcs",
            JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("ad_bind_dn", sa.String(length=512), nullable=True),
        sa.Column("ad_bind_password_enc", sa.LargeBinary(), nullable=True),
        sa.Column("ad_users_search_base", sa.String(length=512), nullable=True),
        sa.Column(
            "ad_sync_interval_minutes",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("15"),
        ),
        # Audit fingerprint
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("updated_by_upn", sa.String(length=320), nullable=True),
        sa.CheckConstraint("id = 1", name="ck_app_settings_app_settings_singleton"),
    )

    # Always insert the singleton row so callers can rely on its existence.
    op.execute(
        "INSERT INTO app_settings (id, version, oidc_scopes, bootstrap_admins, ad_dcs) "
        "VALUES (1, 1, '[]'::jsonb, '[]'::jsonb, '[]'::jsonb) "
        "ON CONFLICT DO NOTHING"
    )


def downgrade() -> None:
    op.drop_table("app_settings")
