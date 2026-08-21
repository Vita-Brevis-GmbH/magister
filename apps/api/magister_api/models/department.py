"""Department model (company edition, M6 Phase 2, ADR-0008 D6).

Parallel to :class:`SchoolClass` — the mid-level org unit for the company
edition (Abteilung/Team). Scoped by ``school_id``, which stays the physical
top-level scope column (an org unit / Standort in the company vocabulary).
Companies have no Jahrgangsstufe/Zyklus, so this is a slimmer sibling.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from magister_api.models.base import Base, utcnow

DEPARTMENT_STATUS_ACTIVE = "active"
DEPARTMENT_STATUS_ARCHIVED = "archived"
ALLOWED_STATUSES: frozenset[str] = frozenset({DEPARTMENT_STATUS_ACTIVE, DEPARTMENT_STATUS_ARCHIVED})


class Department(Base):
    __tablename__ = "departments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    school_id: Mapped[int] = mapped_column(
        ForeignKey("schools.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    kuerzel: Mapped[str | None] = mapped_column(String(32), nullable=True)
    details: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default=DEPARTMENT_STATUS_ACTIVE
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )

    # Active-only name uniqueness per org unit is enforced via a partial unique
    # index in the Alembic migration (mirrors classes).
    __table_args__ = (
        CheckConstraint(
            f"status IN ('{DEPARTMENT_STATUS_ACTIVE}', '{DEPARTMENT_STATUS_ARCHIVED}')",
            name="ck_departments_status",
        ),
    )
