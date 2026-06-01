"""import_jobs + import_staged_rows for CSV imports (M3 US-2).

Two tables that back the Stage → Diff → Apply workflow. Both are
school-scoped via the job row's ``school_id``. Staged rows cascade-delete
with the job.

Revision ID: 0009_import_jobs
Revises: 0008_computers_search_base
Create Date: 2026-06-01
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0009_import_jobs"
down_revision: str | Sequence[str] | None = "0008_computers_search_base"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "import_jobs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "school_id",
            sa.Integer(),
            sa.ForeignKey("schools.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="staged"),
        sa.Column("filename", sa.String(length=256), nullable=True),
        sa.Column("created_by_upn", sa.String(length=320), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("applied_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("summary", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.CheckConstraint(
            "kind IN ('classes', 'class_memberships', 'class_teachers')",
            name="ck_import_jobs_kind",
        ),
        sa.CheckConstraint(
            "status IN ('staged', 'applied', 'cancelled')",
            name="ck_import_jobs_status",
        ),
    )
    op.create_index("ix_import_jobs_school_id", "import_jobs", ["school_id"])

    op.create_table(
        "import_staged_rows",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "job_id",
            sa.Integer(),
            sa.ForeignKey("import_jobs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("row_num", sa.Integer(), nullable=False),
        sa.Column("raw_data", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("action", sa.String(length=16), nullable=False),
        sa.Column("errors", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("applied_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("applied_error", sa.String(length=512), nullable=True),
        sa.CheckConstraint(
            "action IN ('create', 'update', 'skip', 'error')",
            name="ck_import_staged_rows_action",
        ),
    )
    op.create_index("ix_import_staged_rows_job_id", "import_staged_rows", ["job_id"])


def downgrade() -> None:
    op.drop_index("ix_import_staged_rows_job_id", table_name="import_staged_rows")
    op.drop_table("import_staged_rows")
    op.drop_index("ix_import_jobs_school_id", table_name="import_jobs")
    op.drop_table("import_jobs")
