"""app_settings: target OUs for AD account provisioning (student import)

Adds three nullable OU columns to the singleton app_settings row:
- ad_ou_students_zyklus3: OU for students in a Zyklus-3 class (grades 7-9)
- ad_ou_students_other:   OU for all other students (Zyklus 1/2)
- ad_ou_teachers:         OU for provisioned teacher accounts

All nullable — unset means provisioning is refused (no wrong-OU fallback).

Revision ID: 0015_provisioning_ous
Revises: 0014_subject_teacher_roles
Create Date: 2026-07-03
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0015_provisioning_ous"
down_revision: str | Sequence[str] | None = "0014_subject_teacher_roles"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "app_settings", sa.Column("ad_ou_students_zyklus3", sa.String(512), nullable=True)
    )
    op.add_column("app_settings", sa.Column("ad_ou_students_other", sa.String(512), nullable=True))
    op.add_column("app_settings", sa.Column("ad_ou_teachers", sa.String(512), nullable=True))

    # Allow the new 'students' provisioning import kind.
    op.drop_constraint("ck_import_jobs_kind", "import_jobs", type_="check")
    op.create_check_constraint(
        "ck_import_jobs_kind",
        "import_jobs",
        "kind IN ('classes', 'class_memberships', 'class_teachers', 'students')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_import_jobs_kind", "import_jobs", type_="check")
    op.create_check_constraint(
        "ck_import_jobs_kind",
        "import_jobs",
        "kind IN ('classes', 'class_memberships', 'class_teachers')",
    )
    op.drop_column("app_settings", "ad_ou_teachers")
    op.drop_column("app_settings", "ad_ou_students_other")
    op.drop_column("app_settings", "ad_ou_students_zyklus3")
