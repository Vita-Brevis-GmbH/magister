"""Class-teacher (Klassenlehrer) role assignment with sub-role + valid window.

A class can have multiple active KL at the same time:
- ``haupt``  — Hauptverantwortlich
- ``co``     — Co-Klassenlehrer
- ``stellvertretung`` — zeitlich begrenzte Stellvertretung

"Active" = ``valid_from <= now <= COALESCE(valid_to, +infty)`` AND ``revoked_at IS NULL``.

Soft-delete is via ``valid_to``. We keep the row so historical audit references stay valid.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from magister_api.models.base import Base, utcnow

KL_ROLE_HAUPT = "haupt"
KL_ROLE_CO = "co"
KL_ROLE_STELLVERTRETUNG = "stellvertretung"
ALLOWED_KL_ROLES: frozenset[str] = frozenset({KL_ROLE_HAUPT, KL_ROLE_CO, KL_ROLE_STELLVERTRETUNG})


class ClassTeacherRole(Base):
    __tablename__ = "class_teacher_roles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    class_id: Mapped[int] = mapped_column(
        ForeignKey("classes.id", ondelete="RESTRICT"), nullable=False, index=True
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
            f"role IN ('{KL_ROLE_HAUPT}', '{KL_ROLE_CO}', '{KL_ROLE_STELLVERTRETUNG}')",
            name="ck_class_teacher_roles_role",
        ),
        CheckConstraint(
            "valid_to IS NULL OR valid_to >= valid_from",
            name="ck_class_teacher_roles_window",
        ),
    )
