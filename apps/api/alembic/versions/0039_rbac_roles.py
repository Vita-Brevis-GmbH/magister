"""dynamic roles + role→capability matrix (M6 #3, ADR-0010)

Makes the role→capability mapping data instead of the code-fixed
``ROLE_CAPABILITIES`` table. Capabilities stay code-defined. The tables are
created empty; the system roles and the default matrix are seeded idempotently
at app start (``RbacService.seed_defaults_if_empty``), so behaviour after seed
is identical to the previous static map.

Revision ID: 0039_rbac_roles
Revises: 0038_document_templates
Create Date: 2026-08-25
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0039_rbac_roles"
down_revision: str | Sequence[str] | None = "0038_document_templates"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "roles",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("key", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("is_system", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("is_admin", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("is_derived", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_roles_key", "roles", ["key"], unique=True)

    op.create_table(
        "role_capabilities",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "role_key",
            sa.String(length=32),
            sa.ForeignKey("roles.key", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("capability", sa.String(length=64), nullable=False),
        sa.UniqueConstraint("role_key", "capability", name="uq_role_capabilities_role_cap"),
    )
    op.create_index("ix_role_capabilities_role_key", "role_capabilities", ["role_key"])


def downgrade() -> None:
    op.drop_index("ix_role_capabilities_role_key", table_name="role_capabilities")
    op.drop_table("role_capabilities")
    op.drop_index("ix_roles_key", table_name="roles")
    op.drop_table("roles")
