"""tenant_backups + policy + restore_jobs + export_jobs (ADR-0016 D10)

Revision ID: 0006_backup
Revises: 0005_connector
Create Date: 2026-09-09

Buchhaltung über Sicherungen, nicht die Sicherungen selbst. Kein privater
Schlüssel und kein Kundenschlüssel — nur Verweise.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0006_backup"
down_revision: str | None = "0005_connector"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

BACKUP_KIND = ("daily", "pre_migration", "manual", "offboarding")
BACKUP_STATUS = ("running", "written", "verified", "failed", "pruned")
RESTORE_STATE = ("requested", "running", "restored", "switched", "failed", "discarded")
EXPORT_STATE = ("requested", "running", "ready", "downloaded", "expired", "failed")


def upgrade() -> None:
    kind = postgresql.ENUM(*BACKUP_KIND, name="backup_kind")
    status = postgresql.ENUM(*BACKUP_STATUS, name="backup_status")
    restore_state = postgresql.ENUM(*RESTORE_STATE, name="restore_state")
    export_state = postgresql.ENUM(*EXPORT_STATE, name="export_state")

    op.create_table(
        "tenant_backups",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("kind", kind, nullable=False, server_default="daily"),
        sa.Column("status", status, nullable=False, server_default="running"),
        sa.Column("path", sa.String(1000), nullable=False),
        sa.Column("size_bytes", sa.BigInteger, nullable=True),
        sa.Column("checksum_sha256", sa.String(64), nullable=True),
        sa.Column("audit_key_id", sa.String(64), nullable=True),
        sa.Column("schema_version", sa.String(64), nullable=True),
        sa.Column(
            "started_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("verify_detail", sa.String(2000), nullable=True),
        sa.Column("error", sa.String(2000), nullable=True),
    )
    op.create_index("ix_tenant_backups_tenant_id", "tenant_backups", ["tenant_id"])
    op.create_index(
        "ix_tenant_backups_lookup", "tenant_backups", ["tenant_id", "kind", "started_at"]
    )

    op.create_table(
        "tenant_backup_policy",
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("retention_days", sa.Integer, nullable=False, server_default="10"),
        sa.Column("pre_migration_retention_days", sa.Integer, nullable=False, server_default="30"),
        sa.Column("rpo_hours", sa.Integer, nullable=False, server_default="24"),
        sa.Column("rto_hours", sa.Integer, nullable=False, server_default="8"),
        sa.Column("share_root", sa.String(500), nullable=True),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )

    op.create_table(
        "restore_jobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "backup_id",
            postgresql.UUID(as_uuid=True),
            # RESTRICT, nicht CASCADE: die Zeile einer Wiederherstellung soll
            # nicht verschwinden, weil die Sicherung aufgeräumt wurde. Sie ist
            # der Nachweis, dass jemand wiederhergestellt hat.
            sa.ForeignKey("tenant_backups.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("target_schema", sa.String(63), nullable=False),
        sa.Column("state", restore_state, nullable=False, server_default="requested"),
        sa.Column("reason", sa.String(500), nullable=False),
        sa.Column("requested_by", sa.String(200), nullable=False),
        sa.Column("approved_by", sa.String(200), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("switched_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("previous_schema", sa.String(63), nullable=True),
        sa.Column("error", sa.String(2000), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_restore_jobs_tenant_id", "restore_jobs", ["tenant_id"])

    op.create_table(
        "export_jobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("state", export_state, nullable=False, server_default="requested"),
        sa.Column("path", sa.String(1000), nullable=True),
        sa.Column("size_bytes", sa.BigInteger, nullable=True),
        sa.Column("checksum_sha256", sa.String(64), nullable=True),
        sa.Column("requested_by", sa.String(200), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("downloaded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error", sa.String(2000), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_export_jobs_tenant_id", "export_jobs", ["tenant_id"])


def downgrade() -> None:
    op.drop_index("ix_export_jobs_tenant_id", table_name="export_jobs")
    op.drop_table("export_jobs")
    op.drop_index("ix_restore_jobs_tenant_id", table_name="restore_jobs")
    op.drop_table("restore_jobs")
    op.drop_table("tenant_backup_policy")
    for name in ("ix_tenant_backups_lookup", "ix_tenant_backups_tenant_id"):
        op.drop_index(name, table_name="tenant_backups")
    op.drop_table("tenant_backups")
    for enum_name in ("export_state", "restore_state", "backup_status", "backup_kind"):
        op.execute(sa.text(f"DROP TYPE IF EXISTS {enum_name}"))
