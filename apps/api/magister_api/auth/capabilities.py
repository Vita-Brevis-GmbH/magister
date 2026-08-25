"""Capability-based authorization (M6 Phase 3 → #3, ADR-0008 + ADR-0010).

Endpoints declare the *capability* they need — not the role that happens to
hold it today. Capabilities are code-defined (they are wired to endpoints); the
role→capability mapping is **data** (ADR-0010): it lives in ``role_capabilities``
and is loaded per request into an :class:`RbacMatrix`. The ``ROLE_CAPABILITIES``
map below is only the **seed default** used to populate an empty install so that
behaviour after seeding is identical to the former static map.

The ``require_*`` helpers in :mod:`magister_api.auth.rbac` are thin wrappers
over :func:`require_capability`. ``admin`` is the super-role and implicitly
holds every capability.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from enum import StrEnum

from fastapi import Depends, HTTPException, status

from magister_api.auth.current_user import AuthenticatedUser, get_current_user
from magister_api.auth.roles import ROLE_KL, ROLE_SCHULLEITUNG, ROLE_SMI


class Capability(StrEnum):
    """What an endpoint may require. Values are stable dotted identifiers."""

    SYSTEM_ADMINISTER = "system.administer"  # system/config surfaces (admin only)
    ORGUNIT_MANAGE = "orgunit.manage"  # manage classes/teachers/departments in a school
    USER_ADMINISTER = "user.administer"  # provision/edit users + reset passwords
    USER_READ = "user.read"  # list/read users + audit
    USER_CONFIG = "user.config"  # user-config surface (OUs, templates, PW-vault switch)
    IMPORT_RUN = "import.run"  # reach the CSV import endpoints


# Seed default only (ADR-0010): the runtime mapping is the DB matrix. admin is
# the super-role and holds every capability implicitly, so it is not listed. A
# role absent from the map holds no capability (e.g. ``kl``, whose powers are
# per-class and live in :mod:`magister_api.auth.class_perm`).
ROLE_CAPABILITIES: dict[str, frozenset[Capability]] = {
    ROLE_SCHULLEITUNG: frozenset(
        {
            Capability.ORGUNIT_MANAGE,
            Capability.USER_READ,
            Capability.USER_CONFIG,
            Capability.IMPORT_RUN,
        }
    ),
    ROLE_SMI: frozenset(
        {
            Capability.USER_ADMINISTER,
            Capability.USER_READ,
            Capability.USER_CONFIG,
            Capability.IMPORT_RUN,
        }
    ),
    ROLE_KL: frozenset(),
}


@dataclass(frozen=True)
class RbacMatrix:
    """A point-in-time snapshot of the role→capability mapping (ADR-0010).

    ``role_caps`` maps a role key to the capabilities it grants; ``admin_roles``
    is the set of super-role keys that hold every capability implicitly.
    """

    role_caps: dict[str, frozenset[Capability]]
    admin_roles: frozenset[str]

    def holds_admin(self, roles: tuple[str, ...]) -> bool:
        return any(r in self.admin_roles for r in roles)


def effective_capabilities(user: AuthenticatedUser, matrix: RbacMatrix) -> frozenset[Capability]:
    """The capabilities a user holds via their roles (``admin`` ⇒ all)."""
    if user.is_admin or matrix.holds_admin(user.roles):
        return frozenset(Capability)
    caps: set[Capability] = set()
    for role in user.roles:
        caps |= matrix.role_caps.get(role, frozenset())
    return frozenset(caps)


def has_capability(user: AuthenticatedUser, matrix: RbacMatrix, *required: Capability) -> bool:
    """True if the user holds at least one of *required* (``admin`` ⇒ True)."""
    if user.is_admin or matrix.holds_admin(user.roles):
        return True
    held = effective_capabilities(user, matrix)
    return any(cap in held for cap in required)


def require_capability(
    *required: Capability,
) -> Callable[..., Awaitable[AuthenticatedUser]]:
    """FastAPI dependency: the user must hold at least one of *required*.

    ``admin`` always passes (super-role). Mirrors ``require_role``'s any-of
    semantics, but the endpoint names the capability it needs instead of a role.
    The role→capability matrix is loaded per request (ADR-0010).
    """
    if not required:
        raise ValueError("require_capability(): pass at least one capability")

    # Lazy import breaks the capabilities → services.rbac → capabilities cycle.
    from magister_api.services.rbac import get_rbac_matrix

    async def _dep(
        user: AuthenticatedUser = Depends(get_current_user),
        matrix: RbacMatrix = Depends(get_rbac_matrix),
    ) -> AuthenticatedUser:
        if has_capability(user, matrix, *required):
            return user
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="forbidden")

    return _dep
