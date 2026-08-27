"""group templates (Zielrollen) + department AD groups + optional Standort

Adds:
- ``departments.ad_groups`` (JSONB list of AD group DNs applied on membership)
- ``departments.school_id`` becomes nullable (a department may be
  standortübergreifend / not bound to a Standort — "freies Arbeiten")
- ``group_templates`` + ``group_template_schools`` (M2M) — the editable,
  self-serviceable AD-group templates chosen at user-create, filtered by
  Standort. Seeded from each school's existing ``ad_groups_*`` config so nothing
  is stranded when the school form stops editing them.

Revision ID: 0042_group_templates
Revises: 0041_import_kind_company
Create Date: 2026-08-27
"""

from __future__ import annotations

import json
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0042_group_templates"
down_revision: str | Sequence[str] | None = "0041_import_kind_company"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# (kind, source column on schools, seed template name)
_SEED_KINDS: tuple[tuple[str, str, str], ...] = (
    ("teacher", "ad_groups_teacher", "Lehrperson"),
    ("student_zyklus1", "ad_groups_student_zyklus1", "Schüler:in Zyklus 1"),
    ("student_zyklus2", "ad_groups_student_zyklus2", "Schüler:in Zyklus 2"),
    ("student_zyklus3", "ad_groups_student_zyklus3", "Schüler:in Zyklus 3"),
    ("company", "ad_groups_company", "Mitarbeiter:in"),
)


def upgrade() -> None:
    # 1. Departments: direct AD groups + optional Standort binding.
    op.add_column(
        "departments",
        sa.Column(
            "ad_groups",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="[]",
        ),
    )
    op.alter_column("departments", "school_id", existing_type=sa.Integer(), nullable=True)

    # 2. group_templates + M2M link table.
    op.create_table(
        "group_templates",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("kind", sa.String(length=32), nullable=True),
        sa.Column(
            "ad_groups",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="[]",
        ),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="active"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")
        ),
        sa.CheckConstraint(
            "status IN ('active', 'archived')", name="ck_group_templates_status"
        ),
    )
    op.create_table(
        "group_template_schools",
        sa.Column(
            "group_template_id",
            sa.Integer(),
            sa.ForeignKey("group_templates.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "school_id",
            sa.Integer(),
            sa.ForeignKey("schools.id", ondelete="CASCADE"),
            primary_key=True,
        ),
    )
    op.create_index(
        "ix_group_template_schools_school_id", "group_template_schools", ["school_id"]
    )

    # 3. Seed templates from each school's existing per-Zyklus/company group
    #    config, linked to that school, so the config remains editable in the new
    #    surface after the school form stops editing ad_groups_*.
    conn = op.get_bind()
    cols = ", ".join(col for _, col, _ in _SEED_KINDS)
    rows = conn.execute(sa.text(f"SELECT id, {cols} FROM schools")).mappings().all()
    for school in rows:
        for kind, col, label in _SEED_KINDS:
            raw = school[col]
            groups = raw if isinstance(raw, list) else (json.loads(raw) if raw else [])
            if not groups:
                continue
            tid = conn.execute(
                sa.text(
                    "INSERT INTO group_templates (name, kind, ad_groups, status, "
                    "created_at, updated_at) VALUES (:name, :kind, CAST(:groups AS jsonb), "
                    "'active', now(), now()) RETURNING id"
                ),
                {"name": label, "kind": kind, "groups": json.dumps(groups)},
            ).scalar_one()
            conn.execute(
                sa.text(
                    "INSERT INTO group_template_schools (group_template_id, school_id) "
                    "VALUES (:tid, :sid)"
                ),
                {"tid": tid, "sid": school["id"]},
            )


def downgrade() -> None:
    op.drop_index("ix_group_template_schools_school_id", table_name="group_template_schools")
    op.drop_table("group_template_schools")
    op.drop_table("group_templates")
    op.alter_column("departments", "school_id", existing_type=sa.Integer(), nullable=False)
    op.drop_column("departments", "ad_groups")
