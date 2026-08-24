"""document_templates: operator-editable document/mail templates — M6 Feature B

A row overrides the built-in Jinja template for one (key, language, school).
school_id NULL is the instance-wide default. See ADR-0009 D2.

Revision ID: 0038_document_templates
Revises: 0037_user_org_attrs
Create Date: 2026-08-24
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0038_document_templates"
down_revision: str | Sequence[str] | None = "0037_user_org_attrs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "document_templates",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("key", sa.String(length=64), nullable=False),
        sa.Column("language", sa.String(length=8), nullable=False),
        sa.Column("school_id", sa.Integer(), nullable=True),
        sa.Column("subject", sa.String(length=512), nullable=True),
        sa.Column("body_html", sa.Text(), nullable=False, server_default=""),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("updated_by", sa.String(length=320), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["school_id"], ["schools.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_document_templates_key_lang_school",
        "document_templates",
        ["key", "language", "school_id"],
        unique=True,
        postgresql_where=sa.text("school_id IS NOT NULL"),
    )
    op.create_index(
        "ix_document_templates_key_lang_global",
        "document_templates",
        ["key", "language"],
        unique=True,
        postgresql_where=sa.text("school_id IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_document_templates_key_lang_global", table_name="document_templates")
    op.drop_index("ix_document_templates_key_lang_school", table_name="document_templates")
    op.drop_table("document_templates")
