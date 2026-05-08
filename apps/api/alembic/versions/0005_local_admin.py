"""local_admin: break-glass account + sessions.auth_kind

Revision ID: 0005_local_admin
Revises: 0004_class_memberships
Create Date: 2026-05-08
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0005_local_admin"
down_revision: str | Sequence[str] | None = "0004_class_memberships"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "local_admins",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("username", sa.String(length=64), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("failed_login_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("password_changed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("username", name="uq_local_admins_username"),
        sa.CheckConstraint("id = 1", name="ck_local_admins_local_admin_singleton"),
    )

    # Distinguish OIDC sessions from local-admin sessions; existing rows backfill to "oidc".
    op.add_column(
        "sessions",
        sa.Column(
            "auth_kind",
            sa.String(length=16),
            nullable=False,
            server_default="oidc",
        ),
    )


def downgrade() -> None:
    op.drop_column("sessions", "auth_kind")
    op.drop_table("local_admins")
