"""Schulklasse model.

The Python class is named ``SchoolClass`` to avoid shadowing the ``class`` keyword;
the SQL table stays ``classes`` to match SPEC.md §5.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from magister_api.models.base import Base, utcnow

CLASS_STATUS_ACTIVE = "active"
CLASS_STATUS_ARCHIVED = "archived"
ALLOWED_STATUSES: frozenset[str] = frozenset({CLASS_STATUS_ACTIVE, CLASS_STATUS_ARCHIVED})


class SchoolClass(Base):
    __tablename__ = "classes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    school_id: Mapped[int] = mapped_column(
        ForeignKey("schools.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    kuerzel: Mapped[str | None] = mapped_column(String(32), nullable=True)
    # Lower/primary grade. Drives Zyklus/OU routing, sorting and promotion.
    # Kindergarten years are encoded below grade 1: -1 = 1. Kindergarten,
    # 0 = 2. Kindergarten; grades 1..13 as usual.
    jahrgangsstufe: Mapped[int] = mapped_column(Integer, nullable=False)
    # Upper grade for multi-grade classes (Mehrjahrgangsklassen, Basisstufe).
    # NULL means a single-grade class (equivalent to jahrgangsstufe_bis ==
    # jahrgangsstufe). Always >= jahrgangsstufe when set.
    jahrgangsstufe_bis: Mapped[int | None] = mapped_column(Integer, nullable=True)
    details: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default=CLASS_STATUS_ACTIVE)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )

    # Active-only name uniqueness is enforced via a partial unique index in the
    # Alembic migration (cannot be expressed via SQLAlchemy declarative cleanly).
    __table_args__ = (
        CheckConstraint(
            f"status IN ('{CLASS_STATUS_ACTIVE}', '{CLASS_STATUS_ARCHIVED}')",
            name="ck_classes_status",
        ),
    )
