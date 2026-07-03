"""CSV-Import jobs and their staged rows.

Workflow:
- POST /imports uploads a CSV → an ``ImportJob`` is created with ``status=staged``
  and one ``ImportStagedRow`` per data row, each pre-classified with a diff
  ``action`` (create/update/skip/error).
- GET /imports/{id} returns the diff for review.
- POST /imports/{id}/apply runs the staged actions and flips the job to
  ``status=applied``.
- DELETE /imports/{id} marks the job ``cancelled`` (only when ``staged``).

Schul-Scope: every job is bound to a single ``school_id``; Schulleitung sees
only their own jobs, Admin sees all.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, CheckConstraint, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from magister_api.models.base import Base, utcnow

IMPORT_KIND_CLASSES = "classes"
IMPORT_KIND_CLASS_MEMBERSHIPS = "class_memberships"
IMPORT_KIND_CLASS_TEACHERS = "class_teachers"
# Provisioning import: creates NEW AD student accounts (see ADR 0006).
IMPORT_KIND_STUDENTS = "students"
ALLOWED_IMPORT_KINDS: frozenset[str] = frozenset(
    {
        IMPORT_KIND_CLASSES,
        IMPORT_KIND_CLASS_MEMBERSHIPS,
        IMPORT_KIND_CLASS_TEACHERS,
        IMPORT_KIND_STUDENTS,
    }
)

IMPORT_STATUS_STAGED = "staged"
IMPORT_STATUS_APPLIED = "applied"
IMPORT_STATUS_CANCELLED = "cancelled"
ALLOWED_IMPORT_STATUSES: frozenset[str] = frozenset(
    {IMPORT_STATUS_STAGED, IMPORT_STATUS_APPLIED, IMPORT_STATUS_CANCELLED}
)

IMPORT_ACTION_CREATE = "create"
IMPORT_ACTION_UPDATE = "update"
IMPORT_ACTION_SKIP = "skip"
IMPORT_ACTION_ERROR = "error"
ALLOWED_IMPORT_ACTIONS: frozenset[str] = frozenset(
    {IMPORT_ACTION_CREATE, IMPORT_ACTION_UPDATE, IMPORT_ACTION_SKIP, IMPORT_ACTION_ERROR}
)


class ImportJob(Base):
    __tablename__ = "import_jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    school_id: Mapped[int] = mapped_column(
        ForeignKey("schools.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default=IMPORT_STATUS_STAGED)
    filename: Mapped[str | None] = mapped_column(String(256), nullable=True)
    created_by_upn: Mapped[str | None] = mapped_column(String(320), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    summary: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)

    __table_args__ = (
        CheckConstraint(
            "kind IN ('classes', 'class_memberships', 'class_teachers', 'students')",
            name="ck_import_jobs_kind",
        ),
        CheckConstraint(
            "status IN ('staged', 'applied', 'cancelled')",
            name="ck_import_jobs_status",
        ),
    )


class ImportStagedRow(Base):
    __tablename__ = "import_staged_rows"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[int] = mapped_column(
        ForeignKey("import_jobs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    row_num: Mapped[int] = mapped_column(Integer, nullable=False)
    raw_data: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    action: Mapped[str] = mapped_column(String(16), nullable=False)
    errors: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    # Set by the apply step:
    applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    applied_error: Mapped[str | None] = mapped_column(String(512), nullable=True)

    __table_args__ = (
        CheckConstraint(
            "action IN ('create', 'update', 'skip', 'error')",
            name="ck_import_staged_rows_action",
        ),
    )


__all__ = [
    "ALLOWED_IMPORT_ACTIONS",
    "ALLOWED_IMPORT_KINDS",
    "ALLOWED_IMPORT_STATUSES",
    "IMPORT_ACTION_CREATE",
    "IMPORT_ACTION_ERROR",
    "IMPORT_ACTION_SKIP",
    "IMPORT_ACTION_UPDATE",
    "IMPORT_KIND_CLASSES",
    "IMPORT_KIND_CLASS_MEMBERSHIPS",
    "IMPORT_KIND_CLASS_TEACHERS",
    "IMPORT_KIND_STUDENTS",
    "IMPORT_STATUS_APPLIED",
    "IMPORT_STATUS_CANCELLED",
    "IMPORT_STATUS_STAGED",
    "ImportJob",
    "ImportStagedRow",
]
