"""tenants + provisioning_jobs (ADR-0013 D1/D2)

Revision ID: 0004_tenants
Revises: 0003_service_tokens
Create Date: 2026-09-08

Die Mandanten-Registry in der Konsolen-Datenbank. Kein DSN und kein Passwort:
``dsn_ref`` ist ein Verweis, den die Datenebene aus ihrem eigenen
Geheimnisspeicher auflöst.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0004_tenants"
down_revision: str | None = "0003_service_tokens"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TENANT_STATUS = ("provisioning", "active", "suspended", "offboarding")
TENANT_PROFILE = ("school", "company", "neutral")
ISOLATION_MODE = ("schema", "database", "cluster")
JOB_STATUS = ("pending", "running", "failed", "succeeded")
STEPS = ("create_role", "create_schema", "migrate", "data_key", "activate")


def upgrade() -> None:
    tenant_status = postgresql.ENUM(*TENANT_STATUS, name="tenant_status")
    tenant_profile = postgresql.ENUM(*TENANT_PROFILE, name="tenant_profile")
    isolation_mode = postgresql.ENUM(*ISOLATION_MODE, name="tenant_isolation_mode")
    job_status = postgresql.ENUM(*JOB_STATUS, name="provisioning_job_status")
    step = postgresql.ENUM(*STEPS, name="provisioning_step")

    op.create_table(
        "tenants",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("slug", sa.String(31), nullable=False, unique=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("customer_no", sa.String(64), nullable=True),
        sa.Column("hostname", sa.String(253), nullable=False, unique=True),
        sa.Column("status", tenant_status, nullable=False, server_default="provisioning"),
        sa.Column("profile", tenant_profile, nullable=False, server_default="school"),
        sa.Column("isolation_mode", isolation_mode, nullable=False, server_default="schema"),
        sa.Column("dsn_ref", sa.String(64), nullable=False),
        sa.Column("schema_name", sa.String(63), nullable=False),
        sa.Column("db_role", sa.String(63), nullable=False),
        sa.Column("schema_version", sa.String(64), nullable=True),
        sa.Column("suspended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("suspended_reason", sa.String(500), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_tenants_slug", "tenants", ["slug"], unique=True)
    op.create_index("ix_tenants_hostname", "tenants", ["hostname"], unique=True)
    op.create_index("ix_tenants_schema_name", "tenants", ["schema_name"], unique=True)
    op.create_index("ix_tenants_db_role", "tenants", ["db_role"], unique=True)

    op.create_table(
        "provisioning_jobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("status", job_status, nullable=False, server_default="pending"),
        sa.Column("last_completed_step", step, nullable=True),
        sa.Column("steps", postgresql.JSONB, nullable=False, server_default="[]"),
        sa.Column("last_error", sa.String(2000), nullable=True),
        sa.Column("attempts", sa.Integer, nullable=False, server_default="0"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_provisioning_jobs_tenant_id", "provisioning_jobs", ["tenant_id"])


def downgrade() -> None:
    op.drop_index("ix_provisioning_jobs_tenant_id", table_name="provisioning_jobs")
    op.drop_table("provisioning_jobs")
    for name in (
        "ix_tenants_db_role",
        "ix_tenants_schema_name",
        "ix_tenants_hostname",
        "ix_tenants_slug",
    ):
        op.drop_index(name, table_name="tenants")
    op.drop_table("tenants")
    for enum_name in (
        "provisioning_step",
        "provisioning_job_status",
        "tenant_isolation_mode",
        "tenant_profile",
        "tenant_status",
    ):
        op.execute(sa.text(f"DROP TYPE IF EXISTS {enum_name}"))
