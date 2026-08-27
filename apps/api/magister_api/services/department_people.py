"""DepartmentPeopleService: department memberships + manager (Kader) roles.

Scope: the department is looked up through DepartmentRepository (school-scope
filtered); the membership/role repos then trust that check, mirroring how the
class-membership / class-teacher services work.
"""

from __future__ import annotations

import logging
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from magister_api.ad.client import AdClient
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

logger = logging.getLogger(__name__)


def _dedupe_strip(groups: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for g in groups:
        g = (g or "").strip()
        if g and g not in seen:
            seen.add(g)
            out.append(g)
    return out


def groups_to_revoke(removed: list[str], keep: set[str]) -> list[str]:
    """AD groups from the ended membership that no other active membership keeps.

    ``removed`` are the department's AD groups; ``keep`` is the union of AD
    groups still granted by the person's *other* active memberships. Only groups
    in ``removed`` that are not in ``keep`` are revoked, so a group also granted
    elsewhere is never accidentally taken away.
    """
    return [g for g in _dedupe_strip(removed) if g not in keep]


class DepartmentNotInScopeError(LookupError):
    pass


class MembershipNotFoundError(LookupError):
    pass


class ManagerRoleNotFoundError(LookupError):
    pass


class DepartmentPeopleService:
    def __init__(
        self,
        session: AsyncSession,
        settings: Settings,
        scope: ScopeContext,
        ad: AdClient | None = None,
    ) -> None:
        self.session = session
        self.settings = settings
        self.scope = scope
        self.ad = ad
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
        await self._apply_groups(dep, ad_object_guid)
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
        await self._revoke_groups(dep, row.ad_object_guid)
        return row

    # ---------- AD group application ----------

    async def _add_to_ad(self, ad_object_guid: str, groups: list[str]) -> None:
        """Best-effort: add the person to each AD group. Never raises.

        No-op with no groups, no AD client, or mock directory. A directory
        hiccup is logged, not surfaced (parity with provisioning default groups).
        """
        groups = _dedupe_strip(groups)
        if not groups or self.ad is None:
            return
        try:
            user_dn = await self.ad.find_user_dn(ad_object_guid)
            if user_dn is None:
                logger.warning("dept-group apply: user %s not found in AD", ad_object_guid)
                return
            failed = await self.ad.add_user_to_groups(user_dn=user_dn, group_dns=groups)
            if failed:
                logger.warning("dept-group apply: %d group(s) not set for %s", len(failed), user_dn)
        except Exception as exc:  # noqa: BLE001 — never fail the caller on AD trouble
            logger.warning("dept-group apply failed for %s: %s", ad_object_guid, exc)

    async def _revoke_from_ad(self, ad_object_guid: str, groups: list[str]) -> None:
        """Best-effort: remove the person from each AD group. Never raises."""
        groups = _dedupe_strip(groups)
        if not groups or self.ad is None:
            return
        try:
            user_dn = await self.ad.find_user_dn(ad_object_guid)
            if user_dn is None:
                logger.warning("dept-group revoke: user %s not found in AD", ad_object_guid)
                return
            failed = await self.ad.remove_user_from_groups(user_dn=user_dn, group_dns=groups)
            if failed:
                logger.warning(
                    "dept-group revoke: %d group(s) not removed for %s", len(failed), user_dn
                )
        except Exception as exc:  # noqa: BLE001 — never fail the caller on AD trouble
            logger.warning("dept-group revoke failed for %s: %s", ad_object_guid, exc)

    async def _kept_groups(self, ad_object_guid: str) -> set[str]:
        """Union of AD groups still granted by the person's active departments.

        Reads across ALL active memberships (unscoped by design) so a group
        granted by an out-of-scope department is never wrongly revoked, and uses
        the in-session Department rows, so it reflects a just-applied change.
        """
        keep: set[str] = set()
        for m in await self.members.list_active_for_person(ad_object_guid):
            dep = await self.session.get(Department, m.department_id)
            if dep is not None:
                keep.update(_dedupe_strip(list(dep.ad_groups or [])))
        return keep

    async def _apply_groups(self, dep: Department, ad_object_guid: str) -> None:
        """On membership add: grant the department's AD groups."""
        await self._add_to_ad(ad_object_guid, list(dep.ad_groups or []))

    async def _revoke_groups(self, dep: Department, ad_object_guid: str) -> None:
        """On membership end: revoke the department's AD groups the person no
        longer keeps via another still-active membership. The ended membership
        is already closed, so it is excluded from the keep-set."""
        keep = await self._kept_groups(ad_object_guid)
        await self._revoke_from_ad(
            ad_object_guid, groups_to_revoke(list(dep.ad_groups or []), keep)
        )

    async def apply_group_delta(
        self, *, department_id: int, added: list[str], removed: list[str]
    ) -> None:
        """Reconcile all active members after a department's AD groups changed.

        Each active member gets ``added`` granted and ``removed`` revoked —
        except a removed group still granted by another active department of the
        member (matrix orgs). Best-effort; never raises. The department's
        ``ad_groups`` must already hold the NEW set before this is called.
        """
        added = _dedupe_strip(added)
        removed = _dedupe_strip(removed)
        if (not added and not removed) or self.ad is None:
            return
        seen: set[str] = set()
        for m in await self.members.list_active(department_id):
            guid = m.ad_object_guid
            if guid in seen:
                continue
            seen.add(guid)
            if added:
                await self._add_to_ad(guid, added)
            if removed:
                keep = await self._kept_groups(guid)
                await self._revoke_from_ad(guid, groups_to_revoke(removed, keep))

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
