"""user attributes + mail domains for Phase 1 editable-user-attrs feature

Adds eight columns to ``ad_user_cache`` (display_name, sam_account_name,
street_address, locality, postal_code, country, device_name, temp_device_name)
and one column to ``app_settings`` (mail_domains JSONB).

``device_name`` is intended to mirror the Computer-OU lookup result (managedBy=
user-DN) once the AD sync grows that capability (Phase 4). ``temp_device_name``
is Magister-only — never written to AD — used to record a loan device while
the primary is in repair.

Revision ID: 0007_user_attrs
Revises: 0006_app_settings
Create Date: 2026-05-22
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision: str = "0007_user_attrs"
down_revision: str | Sequence[str] | None = "0006_app_settings"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_AD_USER_CACHE_NEW_COLS: tuple[tuple[str, int], ...] = (
    ("display_name", 200),
    ("sam_account_name", 64),
    ("street_address", 200),
    ("locality", 100),
    ("postal_code", 16),
    ("country", 100),
    ("device_name", 100),
    ("temp_device_name", 100),
)


def upgrade() -> None:
    for name, length in _AD_USER_CACHE_NEW_COLS:
        op.add_column(
            "ad_user_cache",
            sa.Column(name, sa.String(length=length), nullable=True),
        )
    # sam_account_name is a likely lookup key for admin tools (resolve a
    # legacy short username); a non-unique index makes that cheap. Not
    # unique because AD scope is per-domain and Magister covers one domain,
    # but a defensive partial unique index would block legitimate renames
    # mid-flight, so plain index only.
    op.create_index(
        "ix_ad_user_cache_sam_account_name",
        "ad_user_cache",
        ["sam_account_name"],
    )

    op.add_column(
        "app_settings",
        sa.Column(
            "mail_domains",
            JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )


def downgrade() -> None:
    op.drop_column("app_settings", "mail_domains")
    op.drop_index("ix_ad_user_cache_sam_account_name", table_name="ad_user_cache")
    for name, _ in reversed(_AD_USER_CACHE_NEW_COLS):
        op.drop_column("ad_user_cache", name)
