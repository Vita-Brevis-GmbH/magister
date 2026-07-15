"""Per-user AD group-membership editing (best-effort LDAP writes + audit).

Backs ``PUT /users/{guid}/groups``. Diffs the desired group DNs against the
user's currently-cached ``ad_groups`` (synced ``memberOf``), then adds/removes
the user in each AD group's ``member`` attribute. Group writes are best-effort:
a refused write (e.g. no "write member" delegation) is logged and reported but
never aborts the whole operation. The resulting cache value reflects what
*actually* changed, so a failed write does not leave the UI showing a group
the user is not in (or missing one they still are).
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import update as sqla_update
from sqlalchemy.ext.asyncio import AsyncSession

from magister_api.ad.client import AdClient
from magister_api.audit.service import AuditService
from magister_api.config import Settings
from magister_api.models.auth import AdUserCache
from magister_api.repositories.base import ScopeContext


class UserNotInAdError(LookupError):
    """No DN was found in AD for the user's objectGUID."""


@dataclass(frozen=True)
class GroupUpdateResult:
    added: list[str]
    removed: list[str]
    failed: list[str]
    groups: list[str]


class UserGroupsService:
    def __init__(
        self,
        session: AsyncSession,
        settings: Settings,
        scope: ScopeContext,
        ad: AdClient,
    ) -> None:
        self.session = session
        self.settings = settings
        self.scope = scope
        self.ad = ad
        self.audit = AuditService(session, settings)

    async def set_groups(
        self,
        *,
        target: AdUserCache,
        desired: list[str],
        ip: str | None,
        request_id: str,
    ) -> GroupUpdateResult:
        current = list(target.ad_groups or [])
        # Normalise the desired set: trim, drop blanks, de-dupe (order-stable).
        seen: set[str] = set()
        desired_norm: list[str] = []
        for dn in desired:
            d = dn.strip()
            if d and d not in seen:
                seen.add(d)
                desired_norm.append(d)

        current_set = set(current)
        desired_set = set(desired_norm)
        to_add = [d for d in desired_norm if d not in current_set]
        to_remove = [d for d in current if d not in desired_set]

        if not to_add and not to_remove:
            return GroupUpdateResult(added=[], removed=[], failed=[], groups=sorted(current_set))

        user_dn = await self.ad.find_user_dn(target.ad_object_guid)
        if not user_dn:
            raise UserNotInAdError(target.ad_object_guid)

        failed_add = await self.ad.add_user_to_groups(user_dn=user_dn, group_dns=to_add)
        failed_remove = await self.ad.remove_user_from_groups(user_dn=user_dn, group_dns=to_remove)

        added_ok = [d for d in to_add if d not in set(failed_add)]
        removed_ok = [d for d in to_remove if d not in set(failed_remove)]
        resulting = sorted((current_set - set(removed_ok)) | set(added_ok))
        failed = sorted(set(failed_add) | set(failed_remove))

        await self.session.execute(
            sqla_update(AdUserCache)
            .where(AdUserCache.ad_object_guid == target.ad_object_guid)
            .values(ad_groups=resulting)
        )

        # Audit the write. Group DNs are not personal data; the allowlist only
        # rejects keys containing password/secret, which these don't.
        await self.audit.emit(
            action="user_groups_changed",
            target_kind="ad_user",
            target_id=target.ad_object_guid,
            actor_upn=self.scope.upn,
            actor_object_guid=self.scope.ad_object_guid,
            school_id=target.school_id,
            ip=ip,
            request_id=request_id,
            payload={
                "added": sorted(added_ok),
                "removed": sorted(removed_ok),
                "failed": failed,
            },
        )
        return GroupUpdateResult(
            added=sorted(added_ok),
            removed=sorted(removed_ok),
            failed=failed,
            groups=resulting,
        )


__all__ = ["GroupUpdateResult", "UserGroupsService", "UserNotInAdError"]
