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

    # --- Plattform-Capabilities (ADR-0017 D5) -----------------------------
    # Was nur der Betreiber darf. Sie stehen in DIESER Aufzählung, damit es
    # eine Liste dotted identifiers gibt — aber sie sind ausdrücklich vom
    # ``admin``-Super-Role ausgenommen (siehe ``PLATFORM_CAPABILITIES``).
    PLATFORM_SETTINGS_MANAGE = "platform.settings.manage"
    PLATFORM_RBAC_MANAGE = "platform.rbac.manage"
    PLATFORM_TENANT_MANAGE = "platform.tenant.manage"
    PLATFORM_MAINTENANCE = "platform.maintenance"


#: Die Capabilities, die **keine Kundenrolle** halten kann — auch nicht
#: ``admin`` (ADR-0017 D5).
#:
#: Das ist keine Vorsicht, sondern eine Korrektur: ``effective_capabilities``
#: gab einem Admin bisher ``frozenset(Capability)``, also **alles, was in der
#: Aufzählung steht**. Wären die Plattform-Rechte einfach dazugekommen, hätte
#: jeder Kunden-Admin sie damit geschenkt bekommen — das Gegenteil der
#: Absicht. Der Super-Role heisst deshalb ab hier „alles, was ein Kunde haben
#: kann" und nicht mehr „alles".
PLATFORM_CAPABILITIES: frozenset[Capability] = frozenset(
    {
        Capability.PLATFORM_SETTINGS_MANAGE,
        Capability.PLATFORM_RBAC_MANAGE,
        Capability.PLATFORM_TENANT_MANAGE,
        Capability.PLATFORM_MAINTENANCE,
    }
)

#: Was eine Kundenrolle überhaupt halten kann.
TENANT_CAPABILITIES: frozenset[Capability] = frozenset(Capability) - PLATFORM_CAPABILITIES


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
    """The capabilities a user holds via their roles.

    ``admin`` is the super-role and holds every **tenant** capability
    implicitly — not the platform ones (ADR-0017 D5). Ein Kunden-Admin ist der
    Administrator seiner Installation und nicht der Betreiber der Plattform.
    """
    if user.operator is not None:
        # Ein Operator-Zugriff (ADR-0019) kommt an jede Leseroute wie ein
        # Kunden-Admin. Dass daraus kein Schreiben wird, leistet die
        # Methodenregel in ``operator_guard`` — und nicht eine kleinere
        # Capability-Menge, die bei jedem neuen Lese-Endpunkt nachgezogen
        # werden müsste.
        return TENANT_CAPABILITIES
    if user.is_admin or matrix.holds_admin(user.roles):
        return TENANT_CAPABILITIES
    caps: set[Capability] = set()
    for role in user.roles:
        caps |= matrix.role_caps.get(role, frozenset())
    # Auch über die Matrix nicht: eine von Hand geschriebene Zeile in
    # ``role_capabilities`` soll keine Plattform-Capability verleihen. Die
    # Prüfung im RBAC-Dienst verhindert das Schreiben; diese hier verhindert
    # die Wirkung, falls die Zeile doch existiert.
    return frozenset(caps) - PLATFORM_CAPABILITIES


def has_capability(user: AuthenticatedUser, matrix: RbacMatrix, *required: Capability) -> bool:
    """True if the user holds at least one of *required*.

    Kein Kurzschluss für ``admin`` mehr: er würde eine Plattform-Capability
    mitgewähren. Der Super-Role wirkt über ``effective_capabilities``.
    """
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
