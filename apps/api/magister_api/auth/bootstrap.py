"""Bootstrap-admin grant on first OIDC login.

Flow (see ARCHITECTURE.md §7):
1. Operator sets ``MAGISTER_BOOTSTRAP_ADMINS=upn1@org,upn2@org``.
2. First OIDC login of a listed UPN → upsert ad_user_cache entry (kind='admin')
   and grant ``role_assignments(role='admin', school_id=NULL)`` if not already.
3. ENV var can be removed afterwards — the role is persistent.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from magister_api.config import Settings
from magister_api.repositories.auth import AdUserCacheRepository, RoleAssignmentRepository


@dataclass(frozen=True)
class BootstrapResult:
    granted: bool
    already_admin: bool


async def maybe_bootstrap_admin(
    *,
    session: AsyncSession,
    settings: Settings,
    upn: str,
    ad_object_guid: str,
    oidc_oid: str | None,
) -> BootstrapResult:
    """If ``upn`` is in ``MAGISTER_BOOTSTRAP_ADMINS``, ensure admin role is granted.

    Returns whether a new grant happened. Idempotent — safe to call on every login.
    """
    bootstrap_set = {u.lower() for u in settings.bootstrap_admins}
    if upn.lower() not in bootstrap_set:
        return BootstrapResult(granted=False, already_admin=False)

    cache_repo = AdUserCacheRepository(session)
    role_repo = RoleAssignmentRepository(session)

    # Ensure the cache row exists so later joins don't break.
    await cache_repo.upsert_admin(
        ad_object_guid=ad_object_guid,
        upn=upn,
        ms_ds_consistency_guid=oidc_oid,
    )

    existing = await role_repo.list_active_for(ad_object_guid)
    if any(r.role == "admin" and r.school_id is None for r in existing):
        return BootstrapResult(granted=False, already_admin=True)

    await role_repo.grant(
        ad_object_guid=ad_object_guid,
        role="admin",
        school_id=None,
        granted_by="bootstrap",
    )
    return BootstrapResult(granted=True, already_admin=False)
