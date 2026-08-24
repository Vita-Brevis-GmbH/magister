"""Company on-/offboarding orchestration (M6 Phase 2).

Onboarding = place an existing user into a department (+ optional manager role).
Offboarding = end all of a person's active department memberships and manager
roles *within the actor's scope*.

Deliberately org-level only: the AD account toggle stays the platform's separate
``PATCH /users/{guid}/status`` endpoint, so this service is AD-free (and thus
unit-testable without an AD connection). A future slice can chain the two.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from magister_api.audit.service import AuditService
from magister_api.config import Settings
from magister_api.models.base import utcnow
from magister_api.models.department import Department
from magister_api.models.department_membership import DepartmentMembership
from magister_api.models.manager_role import ManagerRole
from magister_api.repositories.base import ScopeContext
from magister_api.repositories.department_memberships import DepartmentMembershipRepository
from magister_api.repositories.departments import DepartmentRepository
from magister_api.repositories.manager_roles import ManagerRoleRepository


class DepartmentNotInScopeError(LookupError):
    pass


class CompanyLifecycleService:
    def __init__(self, session: AsyncSession, settings: Settings, scope: ScopeContext) -> None:
        self.session = session
        self.settings = settings
        self.scope = scope
        self.departments = DepartmentRepository(session, scope)
        self.members = DepartmentMembershipRepository(session)
        self.managers = ManagerRoleRepository(session)
        self.audit = AuditService(session, settings)

    async def onboard(
        self,
        *,
        ad_object_guid: str,
        department_id: int,
        role: str | None,
        valid_from: datetime | None,
        ip: str | None,
        request_id: str,
    ) -> tuple[DepartmentMembership, ManagerRole | None]:
        dep = await self.departments.get(department_id)
        if dep is None:
            raise DepartmentNotInScopeError(str(department_id))
        start = valid_from or utcnow()
        membership = await self.members.add(
            department_id=department_id,
            ad_object_guid=ad_object_guid,
            valid_from=start,
            valid_to=None,
            created_by=self.scope.upn,
        )
        manager_role: ManagerRole | None = None
        if role is not None:
            manager_role = await self.managers.add(
                department_id=department_id,
                ad_object_guid=ad_object_guid,
                role=role,
                valid_from=start,
                valid_to=None,
                created_by=self.scope.upn,
            )
        await self.audit.emit(
            action="employee_onboarded",
            target_kind="department",
            target_id=str(department_id),
            actor_upn=self.scope.upn,
            actor_object_guid=self.scope.ad_object_guid,
            school_id=dep.school_id,
            ip=ip,
            request_id=request_id,
            payload={
                "ad_object_guid": ad_object_guid,
                "department_id": department_id,
                "as_manager": role,
            },
        )
        return membership, manager_role

    async def offboard(
        self,
        *,
        ad_object_guid: str,
        ip: str | None,
        request_id: str,
    ) -> tuple[int, int]:
        # scope-bypass: the person's rows are fetched across all departments,
        # then each is re-checked against the actor's scope via
        # can_access_school before being touched.
        memberships = await self.members.list_active_for_person(ad_object_guid)
        roles = await self.managers.list_active_for_person(ad_object_guid)

        memberships_ended = 0
        for m in memberships:
            dep = await self.session.get(Department, m.department_id)
            if dep is not None and self.scope.can_access_school(dep.school_id):
                await self.members.end_now(m)
                memberships_ended += 1

        roles_revoked = 0
        for r in roles:
            dep = await self.session.get(Department, r.department_id)
            if dep is not None and self.scope.can_access_school(dep.school_id):
                await self.managers.end_now(r)
                roles_revoked += 1

        event_school = self.scope.school_scope[0] if len(self.scope.school_scope) == 1 else None
        await self.audit.emit(
            action="employee_offboarded",
            target_kind="user",
            target_id=ad_object_guid,
            actor_upn=self.scope.upn,
            actor_object_guid=self.scope.ad_object_guid,
            school_id=event_school,
            ip=ip,
            request_id=request_id,
            payload={
                "ad_object_guid": ad_object_guid,
                "memberships_ended": memberships_ended,
                "manager_roles_revoked": roles_revoked,
            },
        )
        return memberships_ended, roles_revoked
