"""tenants.audit_key_id + tenant_offboarding (ADR-0016 D8)

Revision ID: 0007_offboarding
Revises: 0006_backup
Create Date: 2026-09-09

Zwei Dinge, beide Verweise und keine Geheimnisse:

* ``tenants.audit_key_id`` — welcher Kundenschlüssel für diesen Kunden gilt.
  Der Schlüssel selbst liegt in der Umgebung des Anwendungsservers. Läge er
  hier, wäre er in der Sicherung der Konsolen-Datenbank, und die zweite
  Verschlüsselungsschicht über den Kunden-Dumps wäre wertlos (ADR-0016 D2).
* ``tenant_offboarding`` — der Ablauf mit seinen Fristen. Die Trennung von
  ``dropped_at`` und ``key_destroyed_at`` ist Absicht: das eine kann die
  Konsole nachweisen, das andere nur festhalten.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0007_offboarding"
down_revision: str | None = "0006_backup"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OFFBOARDING_STATE = (
    "requested",
    "export_ready",
    "dropped",
    "shredded",
    "purged",
    "aborted",
)


def upgrade() -> None:
    op.add_column("tenants", sa.Column("audit_key_id", sa.String(64), nullable=True))

    state = postgresql.ENUM(*OFFBOARDING_STATE, name="offboarding_state", create_type=False)
    state.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "tenant_offboarding",
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("state", state, nullable=False, server_default="requested"),
        sa.Column("reason", sa.String(500), nullable=False),
        sa.Column("requested_by", sa.String(200), nullable=False),
        sa.Column(
            "requested_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("grace_days", sa.Integer(), nullable=False, server_default="30"),
        sa.Column("grace_until", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "final_backup_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenant_backups.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "export_job_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("export_jobs.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("export_delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("dropped_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("dropped_by", sa.String(200), nullable=True),
        sa.Column("approved_by", sa.String(200), nullable=True),
        sa.Column("key_destroyed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("key_destroyed_by", sa.String(200), nullable=True),
        sa.Column("key_id", sa.String(64), nullable=True),
        sa.Column("purge_due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("purged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("aborted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("aborted_reason", sa.String(500), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_table("tenant_offboarding")
    op.execute(sa.text("DROP TYPE IF EXISTS offboarding_state"))
    op.drop_column("tenants", "audit_key_id")
