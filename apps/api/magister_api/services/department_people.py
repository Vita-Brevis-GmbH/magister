"""DepartmentPeopleService: department memberships + manager (Kader) roles.

Scope: the department is looked up through DepartmentRepository (school-scope
filtered); the membership/role repos then trust that check, mirroring how the
class-membership / class-teacher services work.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from magister_api.audit.service import AuditService
from magister_api.config import Settings
from magister_api.models.base import utcnow
from magister_api.models.department import DEPARTMENT_STATUS_ACTIVE, Department
from magister_api.models.department_membership import DepartmentMembership
from magister_api.models.manager_role import ManagerRole
from magister_api.repositories.base import ScopeContext
from magister_api.repositories.department_memberships import DepartmentMembershipRepository
from magister_api.repositories.departments import DepartmentRepository
from magister_api.repositories.manager_roles import ManagerRoleRepository


class DepartmentNotInScopeError(LookupError):
    pass


class MembershipNotFoundError(LookupError):
    pass


class ManagerRoleNotFoundError(LookupError):
    pass


class DepartmentPeopleService:
    def __init__(self, session: AsyncSession, settings: Settings, scope: ScopeContext) -> None:
        self.session = session
        self.settings = settings
        self.scope = scope
        self.departments = DepartmentRepository(session, scope)
        self.members = DepartmentMembershipRepository(session)
        self.managers = ManagerRoleRepository(session)
        self.audit = AuditService(session, settings)

    async def _department(self, department_id: int) -> Department:
        dep = await self.departments.get(department_id)
        if dep is None:
            raise DepartmentNotInScopeError(str(department_id))
        return dep

    # ---------- memberships ----------

    async def list_members(self, department_id: int) -> list[DepartmentMembership]:
        await self._department(department_id)
        return await self.members.list_active(department_id)

    async def list_user_memberships(
        self, ad_object_guid: str
    ) -> list[tuple[DepartmentMembership, Department]]:
        """Active memberships of one person, restricted to in-scope active depts.

        The person's memberships are read across all departments, then each is
        re-checked against the caller's org-unit scope via the scoped
        DepartmentRepository — so a unit admin only sees the departments they may
        manage, and archived departments are dropped.
        """
        rows = await self.members.list_active_for_person(ad_object_guid)
        out: list[tuple[DepartmentMembership, Department]] = []
        for m in rows:
            dep = await self.departments.get(m.department_id)
            if dep is not None and dep.status == DEPARTMENT_STATUS_ACTIVE:
                out.append((m, dep))
        out.sort(key=lambda pair: (pair[1].name, pair[1].id))
        return out

    async def add_member(
        self,
        *,
        department_id: int,
        ad_object_guid: str,
        valid_from: datetime | None,
        valid_to: datetime | None,
        ip: str | None,
        request_id: str,
    ) -> DepartmentMembership:
        dep = await self._department(department_id)
        row = await self.members.add(
            department_id=department_id,
            ad_object_guid=ad_object_guid,
            valid_from=valid_from or utcnow(),
            valid_to=valid_to,
            created_by=self.scope.upn,
        )
        await self.audit.emit(
            action="department_member_added",
            target_kind="department",
            target_id=str(department_id),
            actor_upn=self.scope.upn,
            actor_object_guid=self.scope.ad_object_guid,
            school_id=dep.school_id,
            ip=ip,
            request_id=request_id,
            payload={"ad_object_guid": ad_object_guid, "membership_id": row.id},
        )
        return row

    async def remove_member(
        self,
        *,
        department_id: int,
        membership_id: int,
        ip: str | None,
        request_id: str,
    ) -> DepartmentMembership:
        dep = await self._department(department_id)
        row = await self.members.get(membership_id)
        if row is None or row.department_id != department_id:
            raise MembershipNotFoundError(str(membership_id))
        await self.members.end_now(row)
        await self.audit.emit(
            action="department_member_removed",
            target_kind="department",
            target_id=str(department_id),
            actor_upn=self.scope.upn,
            actor_object_guid=self.scope.ad_object_guid,
            school_id=dep.school_id,
            ip=ip,
            request_id=request_id,
            payload={"ad_object_guid": row.ad_object_guid, "membership_id": membership_id},
        )
        return row

    # ---------- manager (Kader) roles ----------

    async def list_managers(self, department_id: int) -> list[ManagerRole]:
        await self._department(department_id)
        return await self.managers.list_active(department_id)

    async def assign_manager(
        self,
        *,
        department_id: int,
        ad_object_guid: str,
        role: str,
        valid_from: datetime | None,
        valid_to: datetime | None,
        ip: str | None,
        request_id: str,
    ) -> ManagerRole:
        dep = await self._department(department_id)
        row = await self.managers.add(
            department_id=department_id,
            ad_object_guid=ad_object_guid,
            role=role,
            valid_from=valid_from or utcnow(),
            valid_to=valid_to,
            created_by=self.scope.upn,
        )
        await self.audit.emit(
            action="department_manager_assigned",
            target_kind="department",
            target_id=str(department_id),
            actor_upn=self.scope.upn,
            actor_object_guid=self.scope.ad_object_guid,
            school_id=dep.school_id,
            ip=ip,
            request_id=request_id,
            payload={"ad_object_guid": ad_object_guid, "role": role, "role_id": row.id},
        )
        return row

    async def revoke_manager(
        self,
        *,
        department_id: int,
        role_id: int,
        ip: str | None,
        request_id: str,
    ) -> ManagerRole:
        dep = await self._department(department_id)
        row = await self.managers.get(role_id)
        if row is None or row.department_id != department_id:
            raise ManagerRoleNotFoundError(str(role_id))
        await self.managers.end_now(row)
        await self.audit.emit(
            action="department_manager_revoked",
            target_kind="department",
            target_id=str(department_id),
            actor_upn=self.scope.upn,
            actor_object_guid=self.scope.ad_object_guid,
            school_id=dep.school_id,
            ip=ip,
            request_id=request_id,
            payload={"ad_object_guid": row.ad_object_guid, "role": row.role, "role_id": role_id},
        )
        return row
