"""Role-based access control dependencies."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from fastapi import Depends, HTTPException, status

from magister_api.auth.current_user import AuthenticatedUser, get_current_user

# All RBAC tiers visible to routers; "kl" (Klassenlehrer) is derived from
# class_teacher_roles in later issues. M1 foundation only knows admin/schulleitung.
ROLE_ADMIN = "admin"
ROLE_SCHULLEITUNG = "schulleitung"
ROLE_KL = "kl"


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
