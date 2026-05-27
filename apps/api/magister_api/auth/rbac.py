"""Role-based access control dependencies."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from fastapi import Depends, HTTPException, status

from magister_api.auth.current_user import AuthenticatedUser, get_current_user

# RBAC tiers known to routers.
#   admin         — cross-school super-role (school_id=NULL).
#   schulleitung  — per-school; class & teacher management.
#   smi           — per-school Schulträger-IT; cross-school user listing
#                   and password reset for students *and* teachers within
#                   their assigned schools. No system-config powers.
#   kl            — Klassenlehrer; derived from class_teacher_roles (not stored
#                   in role_assignments).
ROLE_ADMIN = "admin"
ROLE_SCHULLEITUNG = "schulleitung"
ROLE_SMI = "smi"
ROLE_KL = "kl"

# Roles that live in ``role_assignments`` (kl is in ``class_teacher_roles``).
ROLE_ASSIGNMENT_ROLES: frozenset[str] = frozenset({ROLE_ADMIN, ROLE_SCHULLEITUNG, ROLE_SMI})


def require_role(
    *allowed: str,
) -> Callable[[AuthenticatedUser], Awaitable[AuthenticatedUser]]:
    """Return a FastAPI dependency that ensures the user has at least one of the given roles.

    ``admin`` always satisfies any role check (super-role).
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


require_admin = require_role(ROLE_ADMIN)
require_schulleitung = require_role(ROLE_ADMIN, ROLE_SCHULLEITUNG)
require_smi = require_role(ROLE_ADMIN, ROLE_SMI)
