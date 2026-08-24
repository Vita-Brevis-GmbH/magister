"""ad_user_cache: organisation/contact attributes — M6 Feature C

Adds title, department, company, telephoneNumber, mobile,
physicalDeliveryOfficeName, description and employeeID — mirrored from AD and
editable via PATCH /users like the address block. See ADR-0009.

Revision ID: 0037_user_org_attrs
Revises: 0036_mail_aliases
Create Date: 2026-08-24
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0037_user_org_attrs"
down_revision: str | Sequence[str] | None = "0036_mail_aliases"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_COLUMNS: tuple[tuple[str, int], ...] = (
    ("title", 128),
    ("department", 200),
    ("company", 200),
    ("telephone_number", 64),
    ("mobile", 64),
    ("office", 200),
    ("description", 1024),
    ("employee_id", 64),
)


def upgrade() -> None:
    for name, length in _COLUMNS:
        op.add_column("ad_user_cache", sa.Column(name, sa.String(length=length), nullable=True))


def downgrade() -> None:
    for name, _ in reversed(_COLUMNS):
        op.drop_column("ad_user_cache", name)
