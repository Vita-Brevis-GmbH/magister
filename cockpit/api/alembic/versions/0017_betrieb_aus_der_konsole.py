"""Betrieb aus der Konsole (ADR-0024).

Vier neue Tabellen, keine Änderung an bestehenden:

* `tenant_status_reports` — letzte Zustandsmeldung der Datenebene je Kunde
* `tenant_sealed_secrets` — versiegelte Geheimnisse (nur Chiffrat)
* `tenant_maintenance_requests` — Wartungsaufträge je Kunde
* `platform_heartbeats` — Lebenszeichen der Helfer (Backup-Prüfer)

Revision ID: 0017_betrieb_aus_der_konsole
Revises: 0016_console_password
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0017_betrieb_aus_der_konsole"
down_revision = "0016_console_password"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "tenant_status_reports",
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "reported_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("payload", postgresql.JSONB(), nullable=False, server_default="{}"),
    )
    op.create_table(
        "tenant_sealed_secrets",
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("name", sa.String(64), primary_key=True),
        sa.Column("ciphertext", sa.Text(), nullable=False),
        sa.Column("key_id", sa.String(64), nullable=False),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("updated_by", sa.String(320), nullable=True),
    )
    op.create_table(
        "tenant_maintenance_requests",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("action", sa.String(32), nullable=False),
        sa.Column("state", sa.String(16), nullable=False, server_default="requested"),
        sa.Column("reason", sa.String(500), nullable=False),
        sa.Column("requested_by", sa.String(320), nullable=False),
        sa.Column(
            "requested_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("result", postgresql.JSONB(), nullable=True),
    )
    op.create_index(
        "ix_tenant_maintenance_requests_tenant_id",
        "tenant_maintenance_requests",
        ["tenant_id"],
    )
    op.create_table(
        "platform_heartbeats",
        sa.Column("name", sa.String(64), primary_key=True),
        sa.Column(
            "last_seen_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("detail", sa.String(2000), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("platform_heartbeats")
    op.drop_index(
        "ix_tenant_maintenance_requests_tenant_id", table_name="tenant_maintenance_requests"
    )
    op.drop_table("tenant_maintenance_requests")
    op.drop_table("tenant_sealed_secrets")
    op.drop_table("tenant_status_reports")
