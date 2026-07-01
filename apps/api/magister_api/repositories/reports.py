"""Read-only aggregate queries backing the ``/reports`` endpoints.

All statements are school-scope filtered via :meth:`BaseRepository.apply_scope`
(admin sees everything; everyone else is narrowed to their ``school_scope``).
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Integer, and_, case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from magister_api.models.audit import AuditEvent
from magister_api.models.auth import AdUserCache
from magister_api.models.base import utcnow
from magister_api.models.class_membership import ClassMembership
from magister_api.models.class_teacher_role import ClassTeacherRole
from magister_api.models.school_class import CLASS_STATUS_ACTIVE, SchoolClass
from magister_api.repositories.base import BaseRepository, ScopeContext
from magister_api.schemas.reports import ActivityRow, StudentsByClassRow, TeacherWorkloadRow


class ReportsRepository(BaseRepository):
    def __init__(self, session: AsyncSession, scope: ScopeContext) -> None:
        super().__init__(session, scope)

    async def students_by_class(self) -> list[StudentsByClassRow]:
        """Count active students per active class, within the caller's scope."""
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
                and_(ClassMembership.class_id == SchoolClass.id, membership_active),
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
        stmt = self.apply_scope(stmt, SchoolClass.school_id)
        rows = (await self.session.execute(stmt)).all()
        return [
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

    async def teacher_workload(self) -> list[TeacherWorkloadRow]:
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
            .outerjoin(AdUserCache, AdUserCache.ad_object_guid == ClassTeacherRole.ad_object_guid)
            .where(role_active)
            .where(SchoolClass.status == CLASS_STATUS_ACTIVE)
            .group_by(ClassTeacherRole.ad_object_guid, AdUserCache.upn, AdUserCache.display_name)
            .order_by(func.count(ClassTeacherRole.id).desc(), AdUserCache.upn)
        )
        stmt = self.apply_scope(stmt, SchoolClass.school_id)
        rows = (await self.session.execute(stmt)).all()
        return [
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

    async def activity(self, *, since: datetime) -> list[ActivityRow]:
        """Top audit actions since ``since``, school-scoped.

        Non-admin callers never see NULL-``school_id`` rows (cross-school admin
        events), because :meth:`apply_scope` narrows to their schools.
        """
        stmt = (
            select(AuditEvent.action, func.count(AuditEvent.id).label("cnt"))
            .where(AuditEvent.ts >= since)
            .group_by(AuditEvent.action)
            .order_by(func.count(AuditEvent.id).desc(), AuditEvent.action)
        )
        stmt = self.apply_scope(stmt, AuditEvent.school_id)
        rows = (await self.session.execute(stmt)).all()
        return [ActivityRow(action=r[0], count=r[1]) for r in rows]


__all__ = ["ReportsRepository"]
