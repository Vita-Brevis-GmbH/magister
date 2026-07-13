"""Purge the operator demo/seed data set.

The ``magister-cli seed-demo`` seed creates a single school ``BSP`` (Schule
Beispiel) with two classes, their memberships and class-teacher rows, plus the
cached demo users under that school. This service removes exactly that, in
FK-safe order (children before the RESTRICT-guarded parents). Audit events that
referenced the school are kept but detached (school_id → NULL) so the audit
trail survives.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

from sqlalchemy import delete, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from magister_api.audit.service import AuditService
from magister_api.config import Settings
from magister_api.models.audit import AuditEvent
from magister_api.models.auth import AdUserCache, RoleAssignment, Session
from magister_api.models.class_membership import ClassMembership
from magister_api.models.class_teacher_role import ClassTeacherRole
from magister_api.models.import_job import ImportJob
from magister_api.models.school import School
from magister_api.models.school_class import SchoolClass
from magister_api.models.subject_teacher_role import SubjectTeacherRole
from magister_api.models.user_preferences import UserPreference

DEMO_SCHOOL_KUERZEL = "BSP"


@dataclass(frozen=True)
class PurgeResult:
    found: bool
    schools: int = 0
    classes: int = 0
    users: int = 0


class DemoDataService:
    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self.session = session
        self.settings = settings
        self.audit = AuditService(session, settings)

    async def purge(
        self,
        *,
        actor_upn: str,
        actor_object_guid: str | None,
        ip: str | None,
        request_id: str,
    ) -> PurgeResult:
        # scope-bypass: demo purge is a global, admin-only maintenance action.
        school = (
            await self.session.execute(
                select(School).where(School.kuerzel == DEMO_SCHOOL_KUERZEL)
            )
        ).scalar_one_or_none()
        if school is None:
            return PurgeResult(found=False)

        class_ids = list(
            (
                await self.session.execute(
                    select(SchoolClass.id).where(SchoolClass.school_id == school.id)
                )
            )
            .scalars()
            .all()
        )
        demo_guids = list(
            (
                await self.session.execute(
                    select(AdUserCache.ad_object_guid).where(AdUserCache.school_id == school.id)
                )
            )
            .scalars()
            .all()
        )

        if class_ids:
            for model in (SubjectTeacherRole, ClassTeacherRole, ClassMembership):
                await self.session.execute(delete(model).where(model.class_id.in_(class_ids)))
            await self.session.execute(delete(SchoolClass).where(SchoolClass.id.in_(class_ids)))

        if demo_guids:
            for model in (Session, UserPreference):
                await self.session.execute(
                    delete(model).where(model.ad_object_guid.in_(demo_guids))
                )

        # role_assignments reference both the user and (for schulleitung/smi)
        # the school — clear either match before the school row goes.
        role_conds = [RoleAssignment.school_id == school.id]
        if demo_guids:
            role_conds.append(RoleAssignment.ad_object_guid.in_(demo_guids))
        await self.session.execute(delete(RoleAssignment).where(or_(*role_conds)))
        await self.session.execute(delete(AdUserCache).where(AdUserCache.school_id == school.id))
        await self.session.execute(delete(ImportJob).where(ImportJob.school_id == school.id))
        # Keep audit history; just detach it from the school we are removing.
        await self.session.execute(
            update(AuditEvent).where(AuditEvent.school_id == school.id).values(school_id=None)
        )
        await self.session.execute(delete(School).where(School.id == school.id))
        await self.session.flush()

        result = PurgeResult(
            found=True, schools=1, classes=len(class_ids), users=len(demo_guids)
        )
        await self.audit.emit(
            action="demo_data_purged",
            target_kind="demo_data",
            target_id=DEMO_SCHOOL_KUERZEL,
            actor_upn=actor_upn,
            actor_object_guid=actor_object_guid,
            school_id=None,
            ip=ip,
            request_id=request_id,
            payload=asdict(result),
        )
        return result


__all__ = ["DEMO_SCHOOL_KUERZEL", "DemoDataService", "PurgeResult"]
