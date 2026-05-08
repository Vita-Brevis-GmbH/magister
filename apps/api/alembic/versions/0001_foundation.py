"""foundation: pgcrypto + audit + auth tables

Revision ID: 0001_foundation
Revises:
Create Date: 2026-04-30
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0001_foundation"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # pgcrypto powers column-level encryption for audit_events.payload.
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")

    op.create_table(
        "schools",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("kuerzel", sa.String(length=50), nullable=False),
        sa.Column("scope_short", sa.String(length=50), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("kuerzel", name="uq_schools_kuerzel"),
    )

    op.create_table(
        "ad_user_cache",
        sa.Column("ad_object_guid", sa.String(length=36), primary_key=True),
        sa.Column(
            "school_id",
            sa.Integer(),
            sa.ForeignKey("schools.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column("upn", sa.String(length=320), nullable=False),
        sa.Column("given_name", sa.String(length=200), nullable=True),
        sa.Column("surname", sa.String(length=200), nullable=True),
        sa.Column("mail", sa.String(length=320), nullable=True),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("last_sync_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ms_ds_consistency_guid", sa.String(length=64), nullable=True),
        sa.UniqueConstraint("upn", name="uq_ad_user_cache_upn"),
    )
    op.create_index("ix_ad_user_cache_school_id", "ad_user_cache", ["school_id"])
    op.create_index("ix_ad_user_cache_kind_enabled", "ad_user_cache", ["kind", "enabled"])
    op.create_index(
        "ix_ad_user_cache_ms_ds_consistency_guid",
        "ad_user_cache",
        ["ms_ds_consistency_guid"],
    )

    op.create_table(
        "sessions",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("ad_object_guid", sa.String(length=36), nullable=False),
        sa.Column("oidc_subject", sa.String(length=255), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "last_seen_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("ip", sa.String(length=64), nullable=True),
        sa.Column("user_agent", sa.String(length=512), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_sessions_ad_object_guid", "sessions", ["ad_object_guid"])

    op.create_table(
        "role_assignments",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("ad_object_guid", sa.String(length=36), nullable=False),
        sa.Column(
            "school_id",
            sa.Integer(),
            sa.ForeignKey("schools.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column("role", sa.String(length=32), nullable=False),
        sa.Column("granted_by", sa.String(length=320), nullable=True),
        sa.Column(
            "granted_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint(
            "ad_object_guid",
            "role",
            "school_id",
            name="uq_role_assignments_user_role_school",
        ),
    )
    op.create_index(
        "ix_role_assignments_ad_object_guid",
        "role_assignments",
        ["ad_object_guid"],
    )
    op.create_index("ix_role_assignments_school_id", "role_assignments", ["school_id"])
    # Partial unique index for the admin (school_id IS NULL) case, since
    # PostgreSQL treats NULLs as distinct in regular unique constraints.
    op.execute(
        "CREATE UNIQUE INDEX ix_role_assignments_admin_unique "
        "ON role_assignments (ad_object_guid, role) "
        "WHERE school_id IS NULL AND revoked_at IS NULL"
    )

    op.create_table(
        "audit_events",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "ts",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("actor_upn", sa.String(length=320), nullable=True),
        sa.Column("actor_object_guid", sa.String(length=36), nullable=True),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("target_kind", sa.String(length=64), nullable=False),
        sa.Column("target_id", sa.String(length=128), nullable=False),
        sa.Column(
            "school_id",
            sa.Integer(),
            sa.ForeignKey("schools.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column("ip", sa.String(length=64), nullable=True),
        sa.Column("request_id", sa.String(length=36), nullable=False),
        sa.Column("payload", sa.LargeBinary(), nullable=False),
    )
    op.create_index("ix_audit_events_ts", "audit_events", ["ts"])
    op.create_index("ix_audit_events_action", "audit_events", ["action"])
    op.create_index("ix_audit_events_school_id", "audit_events", ["school_id"])
    op.create_index("ix_audit_events_target", "audit_events", ["target_kind", "target_id"])


def downgrade() -> None:
    op.drop_index("ix_audit_events_target", table_name="audit_events")
    op.drop_index("ix_audit_events_school_id", table_name="audit_events")
    op.drop_index("ix_audit_events_action", table_name="audit_events")
    op.drop_index("ix_audit_events_ts", table_name="audit_events")
    op.drop_table("audit_events")

    op.execute("DROP INDEX IF EXISTS ix_role_assignments_admin_unique")
    op.drop_index("ix_role_assignments_school_id", table_name="role_assignments")
    op.drop_index("ix_role_assignments_ad_object_guid", table_name="role_assignments")
    op.drop_table("role_assignments")

    op.drop_index("ix_sessions_ad_object_guid", table_name="sessions")
    op.drop_table("sessions")

    op.drop_index("ix_ad_user_cache_ms_ds_consistency_guid", table_name="ad_user_cache")
    op.drop_index("ix_ad_user_cache_kind_enabled", table_name="ad_user_cache")
    op.drop_index("ix_ad_user_cache_school_id", table_name="ad_user_cache")
    op.drop_table("ad_user_cache")

    op.drop_table("schools")

    # pgcrypto is left in place — dropping it could affect other databases
    # sharing the same template; harmless to keep installed.
