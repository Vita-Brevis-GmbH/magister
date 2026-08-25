"""schools: company-user target OU + default groups (#6, company edition)

Adds a single custom-named company-users OU and an optional company default
group list to each Standort. Only used in the company profile; school instances
leave them unset/empty. Additive, no backfill.

Revision ID: 0040_school_company_ou
Revises: 0039_rbac_roles
Create Date: 2026-08-25
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0040_school_company_ou"
down_revision: str | Sequence[str] | None = "0039_rbac_roles"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("schools", sa.Column("ad_ou_company_users", sa.String(length=512), nullable=True))
    op.add_column(
        "schools",
        sa.Column(
            "ad_groups_company",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="[]",
        ),
    )


def downgrade() -> None:
    op.drop_column("schools", "ad_groups_company")
    op.drop_column("schools", "ad_ou_company_users")
