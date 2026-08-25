"""import_jobs: allow the company_users provisioning kind (#7)

Widens the ``ck_import_jobs_kind`` CHECK to accept the new ``company_users``
kind. Drop + recreate (Postgres cannot ALTER a CHECK in place).

Revision ID: 0041_import_kind_company
Revises: 0040_school_company_ou
Create Date: 2026-08-25
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0041_import_kind_company"
down_revision: str | Sequence[str] | None = "0040_school_company_ou"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_OLD = "kind IN ('classes', 'class_memberships', 'class_teachers', 'students', 'teachers')"
_NEW = (
    "kind IN ('classes', 'class_memberships', 'class_teachers', "
    "'students', 'teachers', 'company_users')"
)


def upgrade() -> None:
    op.drop_constraint("ck_import_jobs_kind", "import_jobs", type_="check")
    op.create_check_constraint("ck_import_jobs_kind", "import_jobs", _NEW)


def downgrade() -> None:
    op.drop_constraint("ck_import_jobs_kind", "import_jobs", type_="check")
    op.create_check_constraint("ck_import_jobs_kind", "import_jobs", _OLD)
