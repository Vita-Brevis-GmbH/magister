"""ad_user_cache: mail_aliases (secondary SMTP addresses) — M6 Feature A

Adds the per-user secondary-address list mirrored from AD ``proxyAddresses``.
The primary address stays ``mail``; these are the ``smtp:`` aliases. See
ADR-0009.

Revision ID: 0036_mail_aliases
Revises: 0035_department_people
Create Date: 2026-08-24
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0036_mail_aliases"
down_revision: str | Sequence[str] | None = "0035_department_people"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "ad_user_cache",
        sa.Column(
            "mail_aliases",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )


def downgrade() -> None:
    op.drop_column("ad_user_cache", "mail_aliases")
