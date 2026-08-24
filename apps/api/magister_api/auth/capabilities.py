"""Capability-based authorization (M6 Phase 3, ADR-0008).

Endpoints declare the *capability* they need — not the role that happens to
hold it today. Roles map to capabilities here, in one place: adding a role, or
moving a capability between roles, is a one-line change to
:data:`ROLE_CAPABILITIES` that every endpoint requiring that capability picks
up, with no router edits and no bare role names leaking into feature modules.

The ``require_*`` helpers in :mod:`magister_api.auth.rbac` are thin wrappers
over :func:`require_capability`. ``admin`` is the super-role and implicitly
holds every capability.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
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


# admin is the super-role and implicitly holds every capability, so it is not
# listed. A role absent from the map holds no capability (e.g. ``kl``, whose
# powers are per-class and live in :mod:`magister_api.auth.class_perm`).
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


def effective_capabilities(user: AuthenticatedUser) -> frozenset[Capability]:
    """The capabilities a user holds via their roles (``admin`` ⇒ all)."""
    if user.is_admin:
        return frozenset(Capability)
    caps: set[Capability] = set()
    for role in user.roles:
        caps |= ROLE_CAPABILITIES.get(role, frozenset())
    return frozenset(caps)


def has_capability(user: AuthenticatedUser, *required: Capability) -> bool:
    """True if the user holds at least one of *required* (``admin`` ⇒ True)."""
    if user.is_admin:
        return True
    held = effective_capabilities(user)
    return any(cap in held for cap in required)


def require_capability(
    *required: Capability,
) -> Callable[[AuthenticatedUser], Awaitable[AuthenticatedUser]]:
    """FastAPI dependency: the user must hold at least one of *required*.

    ``admin`` always passes (super-role). Mirrors ``require_role``'s any-of
    semantics, but the endpoint names the capability it needs instead of a role.
    """
    if not required:
        raise ValueError("require_capability(): pass at least one capability")

    async def _dep(user: AuthenticatedUser = Depends(get_current_user)) -> AuthenticatedUser:
        if has_capability(user, *required):
            return user
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="forbidden")

    return _dep
