"""Department membership (company edition, M6 Phase 2).

An employee's membership in a department for a window ``[valid_from,
valid_to|+infty)``. Unlike class memberships (a student is in exactly one active
class), a person MAY be in several departments at once (matrix orgs), so there
is no overlap restriction — closing a membership is a soft end via ``valid_to``.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from magister_api.models.base import Base, utcnow


class DepartmentMembership(Base):
    __tablename__ = "department_memberships"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    department_id: Mapped[int] = mapped_column(
        ForeignKey("departments.id", ondelete="RESTRICT"), nullable=False, index=True
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
            name="ck_department_memberships_window",
        ),
    )
