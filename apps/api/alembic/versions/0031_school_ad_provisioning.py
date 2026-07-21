"""Per-school AD provisioning config

Moves the AD provisioning target-OUs and per-Zyklus group templates from the
global ``app_settings`` singleton onto each school, so the right OUs/GPOs and
group settings apply per Schulhaus. Adds an ``ad_ou_devices`` column for the
school's computer/device OU. Existing global values are copied onto every
current school as a starting point so provisioning keeps working.

The Zyklus boundaries and the password-store switch stay global (on
app_settings); only the OU + group mapping becomes per-school.

Revision ID: 0031_school_ad_provisioning
Revises: 0030_web_tls_cert
Create Date: 2026-07-21
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0031_school_ad_provisioning"
down_revision: str | Sequence[str] | None = "0030_web_tls_cert"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_GROUP_COLS = (
    "ad_groups_teacher",
    "ad_groups_student_zyklus1",
    "ad_groups_student_zyklus2",
    "ad_groups_student_zyklus3",
)


def upgrade() -> None:
    op.add_column(
        "schools", sa.Column("ad_ou_students_zyklus3", sa.String(length=512), nullable=True)
    )
    op.add_column(
        "schools", sa.Column("ad_ou_students_other", sa.String(length=512), nullable=True)
    )
    op.add_column("schools", sa.Column("ad_ou_teachers", sa.String(length=512), nullable=True))
    op.add_column("schools", sa.Column("ad_ou_devices", sa.String(length=512), nullable=True))
    for col in _GROUP_COLS:
        op.add_column(
            "schools",
            sa.Column(
                col,
                postgresql.JSONB(astext_type=sa.Text()),
                nullable=False,
                server_default="[]",
            ),
        )

    # Seed every existing school from the current global values so provisioning
    # keeps working until admins customise each school.
    op.execute(
        """
        UPDATE schools s SET
            ad_ou_students_zyklus3 = a.ad_ou_students_zyklus3,
            ad_ou_students_other   = a.ad_ou_students_other,
            ad_ou_teachers         = a.ad_ou_teachers,
            ad_groups_teacher          = a.ad_groups_teacher,
            ad_groups_student_zyklus1  = a.ad_groups_student_zyklus1,
            ad_groups_student_zyklus2  = a.ad_groups_student_zyklus2,
            ad_groups_student_zyklus3  = a.ad_groups_student_zyklus3
        FROM app_settings a
        WHERE a.id = 1
        """
    )


def downgrade() -> None:
    for col in reversed(_GROUP_COLS):
        op.drop_column("schools", col)
    op.drop_column("schools", "ad_ou_devices")
    op.drop_column("schools", "ad_ou_teachers")
    op.drop_column("schools", "ad_ou_students_other")
    op.drop_column("schools", "ad_ou_students_zyklus3")
