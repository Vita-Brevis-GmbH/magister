"""Manager (Kader) role on a department (company edition, M6 Phase 2).

Parallel to ClassTeacherRole. A department can have multiple active managers:
- ``lead``   — Verantwortliche:r / Kader
- ``deputy`` — Stellvertretung

"Active" = ``valid_from <= now < COALESCE(valid_to, +infty)``. Soft-end via
``valid_to`` keeps history for audit.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from magister_api.models.base import Base, utcnow

MANAGER_ROLE_LEAD = "lead"
MANAGER_ROLE_DEPUTY = "deputy"
ALLOWED_MANAGER_ROLES: frozenset[str] = frozenset({MANAGER_ROLE_LEAD, MANAGER_ROLE_DEPUTY})


class ManagerRole(Base):
    __tablename__ = "manager_roles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    department_id: Mapped[int] = mapped_column(
        ForeignKey("departments.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    ad_object_guid: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    role: Mapped[str] = mapped_column(String(32), nullable=False)
    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    valid_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(320), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )

    __table_args__ = (
        CheckConstraint(
            f"role IN ('{MANAGER_ROLE_LEAD}', '{MANAGER_ROLE_DEPUTY}')",
            name="ck_manager_roles_role",
        ),
        CheckConstraint(
            "valid_to IS NULL OR valid_to >= valid_from",
            name="ck_manager_roles_window",
        ),
    )
