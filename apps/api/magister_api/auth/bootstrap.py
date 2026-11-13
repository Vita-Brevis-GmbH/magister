"""Bootstrap-admin grant on OIDC login (ADR-0025).

Flow:
1. The console sets ``bootstrap_admins`` — Keycloak user names of the realm,
   e.g. ``automato-admin`` (UPN-shaped names keep working: they are user names
   too).
2. Every OIDC login of a listed user name grants
   ``role_assignments(role='admin', school_id=NULL)`` on the login account's
   ``principal_guid`` if not already there — repeatedly, so a revoked grant
   comes back with the next login while the name is listed.
3. No ``oid`` and no row in ``ad_user_cache`` is required: Keycloak holds the
   user, Magister only the authorisation.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from magister_api.config import Settings
from magister_api.repositories.auth import RoleAssignmentRepository


@dataclass(frozen=True)
class BootstrapResult:
    granted: bool
    already_admin: bool


def is_bootstrap_admin(settings: Settings, username: str) -> bool:
    """Steht ``username`` in ``bootstrap_admins``? Vergleich klein, ohne Rand."""
    wanted = {u.strip().lower() for u in settings.bootstrap_admins if u.strip()}
    return username.strip().lower() in wanted


async def maybe_bootstrap_admin(
    *,
    session: AsyncSession,
    settings: Settings,
    username: str,
    principal_guid: str,
) -> BootstrapResult:
    """If ``username`` is in ``bootstrap_admins``, ensure the admin role is granted.

    Returns whether a new grant happened. Idempotent — safe to call on every login.
    """
    if not is_bootstrap_admin(settings, username):
        return BootstrapResult(granted=False, already_admin=False)

    role_repo = RoleAssignmentRepository(session)
    existing = await role_repo.list_active_for(principal_guid)
    if any(r.role == "admin" and r.school_id is None for r in existing):
        return BootstrapResult(granted=False, already_admin=True)

    await role_repo.grant(
        ad_object_guid=principal_guid,
        role="admin",
        school_id=None,
        granted_by="bootstrap",
    )
    return BootstrapResult(granted=True, already_admin=False)
