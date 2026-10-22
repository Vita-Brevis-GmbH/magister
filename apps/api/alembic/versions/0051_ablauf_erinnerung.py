"""Erinnerung vor dem Kennwort-Ablauf: Ablaufdaten, Mailversand, Versandprotokoll

Revision ID: 0051_ablauf_erinnerung
Revises: 0050_tresor_fest
Create Date: 2026-10-22

- ad_user_cache: wann das Kennwort zuletzt gesetzt wurde und wann es abläuft
  (aus pwdLastSet / msDS-UserPasswordExpiryTimeComputed), plus wann der
  Abgleich das zuletzt gelesen hat (NULL = unbekannt, älterer Agent).
- app_settings: Mailversand (SMTP oder Microsoft Graph) und die Erinnerung.
  Das Geheimnis liegt pgcrypto-verschlüsselt in mail_secret_enc.
- password_expiry_notices: je Konto, Ablauf und Schwelle eine Zeile, damit
  jede Erinnerung genau einmal hinausgeht.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0051_ablauf_erinnerung"
down_revision: str | Sequence[str] | None = "0050_tresor_fest"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TS = sa.DateTime(timezone=True)


def upgrade() -> None:
    for col in ("password_last_set", "password_expires_at", "password_info_at"):
        op.add_column("ad_user_cache", sa.Column(col, _TS, nullable=True))
    op.create_index(
        "ix_ad_user_cache_password_expires_at", "ad_user_cache", ["password_expires_at"]
    )

    op.add_column(
        "app_settings",
        sa.Column("mail_transport", sa.String(8), nullable=False, server_default="off"),
    )
    op.add_column("app_settings", sa.Column("mail_from", sa.String(320), nullable=True))
    op.add_column("app_settings", sa.Column("mail_from_name", sa.String(128), nullable=True))
    op.add_column("app_settings", sa.Column("smtp_host", sa.String(255), nullable=True))
    op.add_column("app_settings", sa.Column("smtp_port", sa.Integer(), nullable=True))
    op.add_column(
        "app_settings",
        sa.Column("smtp_security", sa.String(8), nullable=False, server_default="starttls"),
    )
    op.add_column("app_settings", sa.Column("smtp_username", sa.String(320), nullable=True))
    op.add_column("app_settings", sa.Column("graph_tenant_id", sa.String(64), nullable=True))
    op.add_column("app_settings", sa.Column("graph_client_id", sa.String(64), nullable=True))
    op.add_column("app_settings", sa.Column("mail_secret_enc", sa.LargeBinary(), nullable=True))
    op.add_column(
        "app_settings",
        sa.Column(
            "expiry_notice_enabled", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
    )
    op.add_column(
        "app_settings",
        sa.Column(
            "expiry_notice_days",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[14, 7, 1]'::jsonb"),
        ),
    )
    op.create_check_constraint(
        "ck_app_settings_mail_transport_valid",
        "app_settings",
        "mail_transport IN ('off', 'smtp', 'graph')",
    )
    op.create_check_constraint(
        "ck_app_settings_smtp_security_valid",
        "app_settings",
        "smtp_security IN ('starttls', 'tls')",
    )

    op.create_table(
        "password_expiry_notices",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("ad_object_guid", sa.String(36), nullable=False),
        sa.Column("expires_at", _TS, nullable=False),
        sa.Column("threshold_days", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(8), nullable=False),
        sa.Column("recipient", sa.String(320), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", _TS, nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint(
            "ad_object_guid", "expires_at", "threshold_days", name="uq_password_expiry_notice"
        ),
    )
    op.create_index(
        "ix_password_expiry_notices_guid", "password_expiry_notices", ["ad_object_guid"]
    )


def downgrade() -> None:
    op.drop_index("ix_password_expiry_notices_guid", table_name="password_expiry_notices")
    op.drop_table("password_expiry_notices")
    op.drop_constraint("ck_app_settings_smtp_security_valid", "app_settings", type_="check")
    op.drop_constraint("ck_app_settings_mail_transport_valid", "app_settings", type_="check")
    for col in (
        "expiry_notice_days",
        "expiry_notice_enabled",
        "mail_secret_enc",
        "graph_client_id",
        "graph_tenant_id",
        "smtp_username",
        "smtp_security",
        "smtp_port",
        "smtp_host",
        "mail_from_name",
        "mail_from",
        "mail_transport",
    ):
        op.drop_column("app_settings", col)
    op.drop_index("ix_ad_user_cache_password_expires_at", table_name="ad_user_cache")
    for col in ("password_info_at", "password_expires_at", "password_last_set"):
        op.drop_column("ad_user_cache", col)
