"""Subject-teacher (Fachlehrer) assignment: teacher + class + subject + window.

Separate from :class:`ClassTeacherRole` on purpose: a Fachlehrer is NOT a
Klassenlehrer, so this never feeds the KL views (substitutions, workload).
It DOES, however, grant student-password-reset for the students of the class
(see ``auth.class_perm``).

"Active" = ``valid_from <= now <= COALESCE(valid_to, +infty)``. Soft-delete via
``valid_to`` so historical audit references stay valid.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from magister_api.models.base import Base, utcnow


class SubjectTeacherRole(Base):
    __tablename__ = "subject_teacher_roles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    class_id: Mapped[int] = mapped_column(
        ForeignKey("classes.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    ad_object_guid: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    subject: Mapped[str] = mapped_column(String(100), nullable=False)
    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    valid_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(320), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )

    __table_args__ = (
        CheckConstraint(
            "valid_to IS NULL OR valid_to >= valid_from",
            name="ck_subject_teacher_roles_window",
        ),
    )
