"""app_settings: GUI-managed AD LDAPS trust (CA cert import + verify toggle)

Adds two columns so the admin UI can control how the LDAPS connection trusts
the domain-controller certificate:

- ``ad_tls_ca_pem``  — an optional pasted PEM CA bundle the DC cert is verified
  against (public data, not a secret → plain Text, not encrypted).
- ``ad_tls_verify``  — when false, DC-certificate validation is skipped
  (still LDAPS/encrypted, but unauthenticated transport). Defaults to true.

Revision ID: 0018_ad_tls
Revises: 0017_ad_bind_mode
Create Date: 2026-07-11
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0018_ad_tls"
down_revision: str | Sequence[str] | None = "0017_ad_bind_mode"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "app_settings",
        sa.Column("ad_tls_verify", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.add_column(
        "app_settings",
        sa.Column("ad_tls_ca_pem", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("app_settings", "ad_tls_ca_pem")
    op.drop_column("app_settings", "ad_tls_verify")
