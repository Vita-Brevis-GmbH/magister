"""Role-based access control dependencies.

Roles (:mod:`magister_api.auth.roles`) are the identity fact; capabilities
(:mod:`magister_api.auth.capabilities`) are what endpoints require. The
endpoint-facing ``require_*`` helpers here are thin wrappers over
:func:`~magister_api.auth.capabilities.require_capability` — an endpoint asks
for the capability it needs, and :data:`ROLE_CAPABILITIES` decides who holds it
(ADR-0008). The role→capability mapping below each wrapper documents the
concrete roles it resolves to today, so the authorization is unchanged from the
previous role-name gates.

``require_role`` remains for the few call sites that still gate on a concrete
role directly.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from fastapi import Depends, HTTPException, status

from magister_api.auth.capabilities import Capability, require_capability
from magister_api.auth.current_user import AuthenticatedUser, get_current_user
from magister_api.auth.roles import (
    ROLE_ADMIN,
    ROLE_ASSIGNMENT_ROLES,
    ROLE_KL,
    ROLE_SCHULLEITUNG,
    ROLE_SMI,
)

__all__ = [
    "ROLE_ADMIN",
    "ROLE_ASSIGNMENT_ROLES",
    "ROLE_KL",
    "ROLE_SCHULLEITUNG",
    "ROLE_SMI",
    "require_admin",
    "require_manage",
    "require_role",
    "require_schulleitung",
    "require_smi",
]


def require_role(
    *allowed: str,
) -> Callable[[AuthenticatedUser], Awaitable[AuthenticatedUser]]:
    """Return a FastAPI dependency that ensures the user has one of the given roles.

    ``admin`` always satisfies any role check (super-role). Prefer
    :func:`~magister_api.auth.capabilities.require_capability` for new endpoints;
    this stays for gates that are intrinsically about a concrete role.
    """
    if not allowed:
        raise ValueError("require_role(): pass at least one role")

    async def _dep(user: AuthenticatedUser = Depends(get_current_user)) -> AuthenticatedUser:
        if user.is_admin:
            return user
        if any(role in user.roles for role in allowed):
            return user
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="forbidden",
        )

    return _dep


# Thin capability wrappers. The trailing comment names the roles each resolves
# to via ROLE_CAPABILITIES — behaviour is identical to the former role gates.
require_admin = require_capability(Capability.SYSTEM_ADMINISTER)  # admin
require_schulleitung = require_capability(Capability.ORGUNIT_MANAGE)  # admin + schulleitung
require_smi = require_capability(Capability.USER_ADMINISTER)  # admin + smi
# Any management tier (admin / Schulleitung / SMI). Used for the user-config
# surface (provisioning OUs, group templates, password-vault switch), which the
# Schulträger-IT and Schulleitung maintain — not just the system admin.
require_manage = require_capability(Capability.USER_CONFIG)  # admin + schulleitung + smi
