"""connector_agents + connector_enrollments + connector_jobs (ADR-0014)

Revision ID: 0005_connector
Revises: 0004_tenants
Create Date: 2026-09-08

Kein Klartextgeheimnis: der API-Key liegt als argon2id-Hash, das Einmal-Token
als SHA-256. Der private Schlüssel des Agenten entsteht auf dem Agenten und
erreicht die Plattform nie.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0005_connector"
down_revision: str | None = "0004_tenants"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

AGENT_STATUS = ("enrolled", "online", "stale", "revoked")
JOB_STATE = ("queued", "claimed", "done", "failed", "expired")


def upgrade() -> None:
    agent_status = postgresql.ENUM(*AGENT_STATUS, name="connector_agent_status")
    job_state = postgresql.ENUM(*JOB_STATE, name="connector_job_state")

    op.create_table(
        "connector_agents",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("status", agent_status, nullable=False, server_default="enrolled"),
        sa.Column("spki_sha256", sa.String(64), nullable=False, unique=True),
        sa.Column("certificate_serial", sa.String(64), nullable=False),
        sa.Column("certificate_not_after", sa.DateTime(timezone=True), nullable=False),
        sa.Column("api_key_hash", sa.String(255), nullable=False),
        sa.Column("result_hmac_key", sa.String(128), nullable=False),
        sa.Column("agent_version", sa.String(64), nullable=True),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_reason", sa.String(500), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_connector_agents_tenant_id", "connector_agents", ["tenant_id"])
    op.create_index(
        "ix_connector_agents_spki_sha256", "connector_agents", ["spki_sha256"], unique=True
    )

    op.create_table(
        "connector_enrollments",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("agent_name", sa.String(200), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("redeemed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "redeemed_agent_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("connector_agents.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("issued_by", sa.String(200), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_connector_enrollments_tenant_id", "connector_enrollments", ["tenant_id"])
    op.create_index(
        "ix_connector_enrollments_token_hash",
        "connector_enrollments",
        ["token_hash"],
        unique=True,
    )

    op.create_table(
        "connector_jobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "agent_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("connector_agents.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("method", sa.String(64), nullable=False),
        sa.Column("payload", postgresql.JSONB, nullable=True),
        sa.Column("payload_purged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("state", job_state, nullable=False, server_default="queued"),
        sa.Column("result", postgresql.JSONB, nullable=True),
        sa.Column("error", sa.String(2000), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempts", sa.Integer, nullable=False, server_default="0"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_connector_jobs_tenant_id", "connector_jobs", ["tenant_id"])
    op.create_index(
        "ix_connector_jobs_queue", "connector_jobs", ["tenant_id", "state", "created_at"]
    )


def downgrade() -> None:
    for name, table in (
        ("ix_connector_jobs_queue", "connector_jobs"),
        ("ix_connector_jobs_tenant_id", "connector_jobs"),
    ):
        op.drop_index(name, table_name=table)
    op.drop_table("connector_jobs")
    for name, table in (
        ("ix_connector_enrollments_token_hash", "connector_enrollments"),
        ("ix_connector_enrollments_tenant_id", "connector_enrollments"),
    ):
        op.drop_index(name, table_name=table)
    op.drop_table("connector_enrollments")
    for name, table in (
        ("ix_connector_agents_spki_sha256", "connector_agents"),
        ("ix_connector_agents_tenant_id", "connector_agents"),
    ):
        op.drop_index(name, table_name=table)
    op.drop_table("connector_agents")
    for enum_name in ("connector_job_state", "connector_agent_status"):
        op.execute(sa.text(f"DROP TYPE IF EXISTS {enum_name}"))
