"""ad_user_cache: per-student jahrgangsstufe (Magister-only)

Adds a nullable grade level per user so a student's own grade is visible on
their profile, importable, and bumpable during class promotion. Magister-only
(not an AD attribute); the AD sync leaves it untouched.

Revision ID: 0023_student_jahrgangsstufe
Revises: 0022_school_details
Create Date: 2026-07-14
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0023_student_jahrgangsstufe"
down_revision: str | Sequence[str] | None = "0022_school_details"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_KIND_OLD = "kind IN ('classes', 'class_memberships', 'class_teachers', 'students')"
_KIND_NEW = "kind IN ('classes', 'class_memberships', 'class_teachers', 'students', 'teachers')"


def upgrade() -> None:
    op.add_column("ad_user_cache", sa.Column("jahrgangsstufe", sa.Integer(), nullable=True))
    # Allow the new 'teachers' provisioning import kind.
    op.drop_constraint("ck_import_jobs_kind", "import_jobs", type_="check")
    op.create_check_constraint("ck_import_jobs_kind", "import_jobs", _KIND_NEW)


def downgrade() -> None:
    op.drop_constraint("ck_import_jobs_kind", "import_jobs", type_="check")
    op.create_check_constraint("ck_import_jobs_kind", "import_jobs", _KIND_OLD)
    op.drop_column("ad_user_cache", "jahrgangsstufe")
