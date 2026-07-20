"""Web-server TLS certificate import

Adds two columns to the ``app_settings`` singleton for an imported webserver
certificate: ``web_tls_cert_pem`` (public chain, plain Text) and
``web_tls_key_enc`` (pgcrypto-encrypted private key). Both NULL = Caddy falls
back to its self-signed internal CA.

Revision ID: 0030_web_tls_cert
Revises: 0029_device_assignment_history
Create Date: 2026-07-20
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0030_web_tls_cert"
down_revision: str | Sequence[str] | None = "0029_device_assignment_history"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("app_settings", sa.Column("web_tls_cert_pem", sa.Text(), nullable=True))
    op.add_column("app_settings", sa.Column("web_tls_key_enc", sa.LargeBinary(), nullable=True))


def downgrade() -> None:
    op.drop_column("app_settings", "web_tls_key_enc")
    op.drop_column("app_settings", "web_tls_cert_pem")
