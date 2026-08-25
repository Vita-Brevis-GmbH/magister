"""Dynamic role + capability-matrix service (M6 #3, ADR-0010).

Loads the role→capability matrix from the DB (:class:`RbacMatrix`), seeds the
system roles + default matrix idempotently at app start, and backs the
``/admin/rbac`` editing endpoints. The matrix is loaded per request via
:func:`get_rbac_matrix` — no in-process cache, so a rights change takes effect
immediately (ADR-0010).
"""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import Depends
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from magister_api.auth.capabilities import ROLE_CAPABILITIES, Capability, RbacMatrix
from magister_api.auth.roles import ROLE_ADMIN, ROLE_KL, ROLE_SCHULLEITUNG, ROLE_SMI
from magister_api.db import get_session
from magister_api.models.rbac import Role, RoleCapability

# Valid capability string values (DB rows outside this set are ignored on load —
# the DB can never grant a capability the code does not define).
_VALID_CAPS: frozenset[str] = frozenset(c.value for c in Capability)


@dataclass(frozen=True)
class _SeedRole:
    key: str
    name: str
    is_admin: bool = False
    is_derived: bool = False


# System roles seeded on an empty install. Names are default labels; the
# frontend translates the built-ins by key. ``admin`` is the super-role (all
# caps implicit); ``kl`` is derived from class_teacher_roles (not assignable).
SEED_ROLES: tuple[_SeedRole, ...] = (
    _SeedRole(key=ROLE_ADMIN, name="Administrator", is_admin=True),
    _SeedRole(key=ROLE_SCHULLEITUNG, name="Schulleitung"),
    _SeedRole(key=ROLE_SMI, name="Schulträger-IT (SMI)"),
    _SeedRole(key=ROLE_KL, name="Klassenlehrer", is_derived=True),
)


class RoleError(Exception):
    """Base for role-mutation errors → mapped to HTTP codes in the router."""


class RoleNotFoundError(RoleError):
    pass


class RoleImmutableError(RoleError):
    """A system/derived/admin role that must not be mutated the requested way."""


class RoleConflictError(RoleError):
    """Duplicate role key."""


class RbacService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # -- seed ---------------------------------------------------------------
    async def seed_defaults_if_empty(self) -> None:
        """Populate system roles + the default matrix once, idempotently."""
        exists = await self.session.scalar(select(Role.id).limit(1))
        if exists is not None:
            return
        for spec in SEED_ROLES:
            self.session.add(
                Role(
                    key=spec.key,
                    name=spec.name,
                    is_system=True,
                    is_admin=spec.is_admin,
                    is_derived=spec.is_derived,
                )
            )
        for role_key, caps in ROLE_CAPABILITIES.items():
            for cap in caps:
                self.session.add(RoleCapability(role_key=role_key, capability=cap.value))
        await self.session.flush()

    # -- read ---------------------------------------------------------------
    async def load_matrix(self) -> RbacMatrix:
        roles = list((await self.session.execute(select(Role))).scalars().all())
        cap_rows = list((await self.session.execute(select(RoleCapability))).scalars().all())
        by_role: dict[str, set[Capability]] = {}
        for row in cap_rows:
            if row.capability in _VALID_CAPS:
                by_role.setdefault(row.role_key, set()).add(Capability(row.capability))
        role_caps = {k: frozenset(v) for k, v in by_role.items()}
        admin_roles = frozenset(r.key for r in roles if r.is_admin)
        return RbacMatrix(role_caps=role_caps, admin_roles=admin_roles)

    async def list_roles(self) -> list[Role]:
        stmt = select(Role).order_by(Role.is_system.desc(), Role.key)
        return list((await self.session.execute(stmt)).scalars().all())

    async def get_role(self, key: str) -> Role | None:
        return await self.session.scalar(select(Role).where(Role.key == key))

    async def capabilities_by_role(self) -> dict[str, list[str]]:
        rows = list((await self.session.execute(select(RoleCapability))).scalars().all())
        out: dict[str, list[str]] = {}
        for row in rows:
            out.setdefault(row.role_key, []).append(row.capability)
        return out

    # -- write --------------------------------------------------------------
    async def create_role(self, *, key: str, name: str) -> Role:
        if await self.get_role(key) is not None:
            raise RoleConflictError(key)
        role = Role(key=key, name=name, is_system=False, is_admin=False, is_derived=False)
        self.session.add(role)
        await self.session.flush()
        return role

    async def rename_role(self, key: str, name: str) -> Role:
        role = await self._require_role(key)
        role.name = name
        await self.session.flush()
        return role

    async def set_capabilities(self, key: str, capabilities: list[Capability]) -> Role:
        role = await self._require_role(key)
        if role.is_admin:
            raise RoleImmutableError("admin holds every capability implicitly")
        if role.is_derived:
            raise RoleImmutableError("derived roles hold no coarse capability")
        await self.session.execute(delete(RoleCapability).where(RoleCapability.role_key == key))
        for cap in dict.fromkeys(capabilities):  # de-dup, keep order
            self.session.add(RoleCapability(role_key=key, capability=cap.value))
        await self.session.flush()
        return role

    async def delete_role(self, key: str) -> None:
        role = await self._require_role(key)
        if role.is_system:
            raise RoleImmutableError("system roles cannot be deleted")
        # role_capabilities rows cascade via the FK; role_assignments referencing
        # this key are left as-is (the role simply no longer grants anything).
        await self.session.delete(role)
        await self.session.flush()

    async def _require_role(self, key: str) -> Role:
        role = await self.get_role(key)
        if role is None:
            raise RoleNotFoundError(key)
        return role


async def get_rbac_matrix(session: AsyncSession = Depends(get_session)) -> RbacMatrix:
    """FastAPI dependency: the current role→capability matrix (per request)."""
    return await RbacService(session).load_matrix()
