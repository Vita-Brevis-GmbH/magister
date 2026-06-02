"""Reporting endpoints — read-only aggregates (M3 US-3).

All endpoints are school-scoped and limited to Admin/Schulleitung/SMI.
Aggregations only — no PII enrichment beyond what the audit log already
exposes via /audit/events.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import Integer, and_, case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from magister_api.auth.current_user import AuthenticatedUser
from magister_api.auth.rbac import require_schulleitung
from magister_api.config import Settings, get_settings
from magister_api.db import get_session
from magister_api.models.audit import AuditEvent
from magister_api.models.auth import AdUserCache
from magister_api.models.base import utcnow
from magister_api.models.class_membership import ClassMembership
from magister_api.models.class_teacher_role import ClassTeacherRole
from magister_api.models.school_class import CLASS_STATUS_ACTIVE, SchoolClass

router = APIRouter(prefix="/reports", tags=["reports"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class StudentsByClassRow(BaseModel):
    class_id: int
    school_id: int
    name: str
    kuerzel: str | None
    jahrgangsstufe: int
    student_count: int


class StudentsByClassReport(BaseModel):
    rows: list[StudentsByClassRow]
    total_students: int
    total_classes: int


class TeacherWorkloadRow(BaseModel):
    ad_object_guid: str
    upn: str | None
    display_name: str | None
    haupt_count: int
    co_count: int
    stellvertretung_count: int
    total: int


class TeacherWorkloadReport(BaseModel):
    rows: list[TeacherWorkloadRow]


class ActivityRow(BaseModel):
    action: str
    count: int


class ActivityReport(BaseModel):
    since: datetime
    rows: list[ActivityRow]


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


def _school_scope(user: AuthenticatedUser) -> list[int] | None:
    """Return None for admin (no implicit narrowing), else the list of schools."""
    return None if user.is_admin else list(user.school_scope)


@router.get("/students-by-class", response_model=StudentsByClassReport)
async def students_by_class(
    user: AuthenticatedUser = Depends(require_schulleitung),
    settings: Settings = Depends(get_settings),
    session: AsyncSession = Depends(get_session),
) -> StudentsByClassReport:
    """Count active students per active class, within the caller's school scope."""
    now = utcnow()
    membership_active = and_(
        ClassMembership.valid_from <= now,
        or_(ClassMembership.valid_to.is_(None), ClassMembership.valid_to > now),
    )
    stmt = (
        select(
            SchoolClass.id,
            SchoolClass.school_id,
            SchoolClass.name,
            SchoolClass.kuerzel,
            SchoolClass.jahrgangsstufe,
            func.count(ClassMembership.id).label("student_count"),
        )
        .select_from(SchoolClass)
        .outerjoin(
            ClassMembership,
            and_(
                ClassMembership.class_id == SchoolClass.id,
                membership_active,
            ),
        )
        .where(SchoolClass.status == CLASS_STATUS_ACTIVE)
        .group_by(
            SchoolClass.id,
            SchoolClass.school_id,
            SchoolClass.name,
            SchoolClass.kuerzel,
            SchoolClass.jahrgangsstufe,
        )
        .order_by(SchoolClass.jahrgangsstufe, SchoolClass.name)
    )
    scope = _school_scope(user)
    if scope is not None:
        stmt = stmt.where(SchoolClass.school_id.in_(scope))

    rows = (await session.execute(stmt)).all()
    out_rows = [
        StudentsByClassRow(
            class_id=r[0],
            school_id=r[1],
            name=r[2],
            kuerzel=r[3],
            jahrgangsstufe=r[4],
            student_count=r[5],
        )
        for r in rows
    ]
    return StudentsByClassReport(
        rows=out_rows,
        total_students=sum(r.student_count for r in out_rows),
        total_classes=len(out_rows),
    )


@router.get("/teacher-workload", response_model=TeacherWorkloadReport)
async def teacher_workload(
    user: AuthenticatedUser = Depends(require_schulleitung),
    settings: Settings = Depends(get_settings),
    session: AsyncSession = Depends(get_session),
) -> TeacherWorkloadReport:
    """Count active class-teacher roles per teacher, broken down by role."""
    now = utcnow()
    role_active = and_(
        ClassTeacherRole.valid_from <= now,
        or_(ClassTeacherRole.valid_to.is_(None), ClassTeacherRole.valid_to > now),
    )

    haupt = func.sum(case((ClassTeacherRole.role == "haupt", 1), else_=0)).cast(Integer)
    co = func.sum(case((ClassTeacherRole.role == "co", 1), else_=0)).cast(Integer)
    stv = func.sum(case((ClassTeacherRole.role == "stellvertretung", 1), else_=0)).cast(Integer)

    stmt = (
        select(
            ClassTeacherRole.ad_object_guid,
            AdUserCache.upn,
            AdUserCache.display_name,
            haupt.label("haupt_count"),
            co.label("co_count"),
            stv.label("stv_count"),
            func.count(ClassTeacherRole.id).label("total"),
        )
        .select_from(ClassTeacherRole)
        .join(SchoolClass, SchoolClass.id == ClassTeacherRole.class_id)
        .outerjoin(
            AdUserCache,
            AdUserCache.ad_object_guid == ClassTeacherRole.ad_object_guid,
        )
        .where(role_active)
        .where(SchoolClass.status == CLASS_STATUS_ACTIVE)
        .group_by(ClassTeacherRole.ad_object_guid, AdUserCache.upn, AdUserCache.display_name)
        .order_by(func.count(ClassTeacherRole.id).desc(), AdUserCache.upn)
    )
    scope = _school_scope(user)
    if scope is not None:
        stmt = stmt.where(SchoolClass.school_id.in_(scope))

    rows = (await session.execute(stmt)).all()
    return TeacherWorkloadReport(
        rows=[
            TeacherWorkloadRow(
                ad_object_guid=r[0],
                upn=r[1],
                display_name=r[2],
                haupt_count=r[3] or 0,
                co_count=r[4] or 0,
                stellvertretung_count=r[5] or 0,
                total=r[6],
            )
            for r in rows
        ]
    )


@router.get("/activity", response_model=ActivityReport)
async def activity(
    days: int = Query(default=30, ge=1, le=365),
    user: AuthenticatedUser = Depends(require_schulleitung),
    settings: Settings = Depends(get_settings),
    session: AsyncSession = Depends(get_session),
) -> ActivityReport:
    """Top audit actions in the last N days, school-scoped (non-admin only sees own school)."""
    since = utcnow() - timedelta(days=days)
    stmt = (
        select(AuditEvent.action, func.count(AuditEvent.id).label("cnt"))
        .where(AuditEvent.ts >= since)
        .group_by(AuditEvent.action)
        .order_by(func.count(AuditEvent.id).desc(), AuditEvent.action)
    )
    if not user.is_admin:
        # Non-admin: hard-restrict to their schools. NULL school_id rows
        # (cross-school admin events) are never returned.
        stmt = stmt.where(AuditEvent.school_id.in_(list(user.school_scope)))

    rows = (await session.execute(stmt)).all()
    return ActivityReport(
        since=since,
        rows=[ActivityRow(action=r[0], count=r[1]) for r in rows],
    )


__all__ = ["router"]
