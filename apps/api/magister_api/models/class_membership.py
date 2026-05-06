"""Student class membership.

A row represents a student's attendance in a class for a time window
``[valid_from, valid_to|+infty)``. Mid-year switches close the previous
membership (set ``valid_to``) and open a new one. Overlap is forbidden:
at any moment a student belongs to at most one active class.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from magister_api.models.base import Base, utcnow


class ClassMembership(Base):
    __tablename__ = "class_memberships"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    class_id: Mapped[int] = mapped_column(
        ForeignKey("classes.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    ad_object_guid: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    valid_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(320), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )

    __table_args__ = (
        CheckConstraint(
            "valid_to IS NULL OR valid_to >= valid_from",
            name="ck_class_memberships_window",
        ),
    )
