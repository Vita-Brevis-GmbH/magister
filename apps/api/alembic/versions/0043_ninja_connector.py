"""NinjaOne connector credentials on app_settings (ADR-0012)

Adds the GUI-editable, encrypted NinjaOne connector config to the app_settings
singleton — mirrors the OIDC/AD secret pattern (the client secret is stored as
pgcrypto-encrypted bytes). NinjaOne *device data* is never persisted; only these
credentials are.

- ``app_settings.ninja_enabled`` (bool, default false)
- ``app_settings.ninja_region`` (text, nullable — us/us2/eu/ca/oc)
- ``app_settings.ninja_client_id`` (text, nullable)
- ``app_settings.ninja_client_secret_enc`` (bytea, nullable)

Revision ID: 0043_ninja_connector
Revises: 0042_group_templates
Create Date: 2026-09-07
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0043_ninja_connector"
down_revision: str | Sequence[str] | None = "0042_group_templates"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "app_settings",
        sa.Column("ninja_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column("app_settings", sa.Column("ninja_region", sa.String(length=8), nullable=True))
    op.add_column(
        "app_settings", sa.Column("ninja_client_id", sa.String(length=255), nullable=True)
    )
    op.add_column(
        "app_settings", sa.Column("ninja_client_secret_enc", sa.LargeBinary(), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("app_settings", "ninja_client_secret_enc")
    op.drop_column("app_settings", "ninja_client_id")
    op.drop_column("app_settings", "ninja_region")
    op.drop_column("app_settings", "ninja_enabled")
