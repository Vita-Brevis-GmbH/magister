"""Reporting endpoints — read-only aggregates (M3 US-3).

All endpoints are school-scoped and limited to Admin/Schulleitung/SMI.
Aggregations only — no PII enrichment beyond what the audit log already
exposes via /audit/events. The actual queries live in ReportsRepository;
these handlers only shape the response.
"""

from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from magister_api.auth.current_user import AuthenticatedUser
from magister_api.auth.rbac import require_schulleitung
from magister_api.db import get_session
from magister_api.models.base import utcnow
from magister_api.repositories.reports import ReportsRepository
from magister_api.schemas.reports import (
    ActivityReport,
    StudentsByClassReport,
    StudentsBySchoolYearReport,
    TeacherWorkloadReport,
)

router = APIRouter(prefix="/reports", tags=["reports"])


@router.get("/students-by-class", response_model=StudentsByClassReport)
async def students_by_class(
    user: AuthenticatedUser = Depends(require_schulleitung),
    session: AsyncSession = Depends(get_session),
) -> StudentsByClassReport:
    rows = await ReportsRepository(session, user.to_scope()).students_by_class()
    return StudentsByClassReport(
        rows=rows,
        total_students=sum(r.student_count for r in rows),
        total_classes=len(rows),
    )


@router.get("/students-by-school-year", response_model=StudentsBySchoolYearReport)
async def students_by_school_year(
    user: AuthenticatedUser = Depends(require_schulleitung),
    session: AsyncSession = Depends(get_session),
) -> StudentsBySchoolYearReport:
    """How many students are in each grade year (Schuljahr), school-scoped."""
    rows = await ReportsRepository(session, user.to_scope()).students_by_school_year()
    return StudentsBySchoolYearReport(
        rows=rows,
        total_students=sum(r.student_count for r in rows),
    )


@router.get("/teacher-workload", response_model=TeacherWorkloadReport)
async def teacher_workload(
    user: AuthenticatedUser = Depends(require_schulleitung),
    session: AsyncSession = Depends(get_session),
) -> TeacherWorkloadReport:
    rows = await ReportsRepository(session, user.to_scope()).teacher_workload()
    return TeacherWorkloadReport(rows=rows)


@router.get("/activity", response_model=ActivityReport)
async def activity(
    days: int = Query(default=30, ge=1, le=365),
    user: AuthenticatedUser = Depends(require_schulleitung),
    session: AsyncSession = Depends(get_session),
) -> ActivityReport:
    """Top audit actions in the last N days, school-scoped (non-admin only sees own school)."""
    since = utcnow() - timedelta(days=days)
    rows = await ReportsRepository(session, user.to_scope()).activity(since=since)
    return ActivityReport(since=since, rows=rows)


__all__ = ["router"]
