"""Admin surface for the dynamic role→capability matrix (`/admin/rbac`).

Lets an admin edit the capabilities of a role, add custom roles and remove them
— the rights matrix of ADR-0010. Admin-only. Every mutation writes an audit
event. Invariants are enforced server-side: the ``admin`` super-role is neither
editable nor deletable, system roles are not deletable, and derived roles
(``kl``) hold no coarse capability.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from magister_api.audit.service import AuditService
from magister_api.auth.capabilities import Capability
from magister_api.auth.current_user import AuthenticatedUser
from magister_api.auth.rbac import require_admin
from magister_api.config import Settings, get_settings
from magister_api.db import get_session
from magister_api.models.rbac import Role
from magister_api.routers._helpers import _ip_request_id
from magister_api.schemas.rbac import (
    RbacConfigOut,
    RoleCapabilitiesUpdate,
    RoleCreate,
    RoleOut,
    RoleRename,
)
from magister_api.services.rbac import (
    RbacService,
    RoleConflictError,
    RoleImmutableError,
    RoleNotFoundError,
)

router = APIRouter(prefix="/admin/rbac", tags=["admin"])


def _role_out(role: Role, caps: list[str]) -> RoleOut:
    editable = not role.is_admin and not role.is_derived
    return RoleOut(
        key=role.key,
        name=role.name,
        is_system=role.is_system,
        is_admin=role.is_admin,
        is_derived=role.is_derived,
        editable=editable,
        renamable=not role.is_system,
        deletable=not role.is_system,
        capabilities=sorted(caps),
    )


async def _config(svc: RbacService) -> RbacConfigOut:
    roles = await svc.list_roles()
    caps_by_role = await svc.capabilities_by_role()
    return RbacConfigOut(
        capabilities=[c.value for c in Capability],
        roles=[_role_out(r, caps_by_role.get(r.key, [])) for r in roles],
    )


async def _emit(
    session: AsyncSession,
    settings: Settings,
    request: Request,
    user: AuthenticatedUser,
    *,
    action: str,
    role_key: str,
    payload: dict[str, object],
) -> None:
    ip, request_id = _ip_request_id(request)
    await AuditService(session, settings).emit(
        action=action,
        target_kind="role",
        target_id=role_key,
        actor_upn=user.upn,
        actor_object_guid=user.ad_object_guid,
        school_id=None,
        ip=ip,
        request_id=request_id,
        payload=payload,
    )


@router.get("", response_model=RbacConfigOut)
async def get_rbac(
    user: AuthenticatedUser = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
) -> RbacConfigOut:
    return await _config(RbacService(session))


@router.post("/roles", response_model=RoleOut, status_code=status.HTTP_201_CREATED)
async def create_role(
    payload: RoleCreate,
    request: Request,
    user: AuthenticatedUser = Depends(require_admin),
    settings: Settings = Depends(get_settings),
    session: AsyncSession = Depends(get_session),
) -> RoleOut:
    svc = RbacService(session)
    try:
        role = await svc.create_role(key=payload.key, name=payload.name)
    except RoleConflictError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, "role_exists") from exc
    await _emit(
        session,
        settings,
        request,
        user,
        action="rbac_role_created",
        role_key=role.key,
        payload={"name": role.name},
    )
    return _role_out(role, [])


@router.patch("/roles/{key}", response_model=RoleOut)
async def rename_role(
    key: str,
    payload: RoleRename,
    request: Request,
    user: AuthenticatedUser = Depends(require_admin),
    settings: Settings = Depends(get_settings),
    session: AsyncSession = Depends(get_session),
) -> RoleOut:
    svc = RbacService(session)
    role = await _lookup(svc, key)
    if role.is_system:
        raise HTTPException(status.HTTP_409_CONFLICT, "system_role_not_renamable")
    role = await svc.rename_role(key, payload.name)
    await _emit(
        session,
        settings,
        request,
        user,
        action="rbac_role_renamed",
        role_key=key,
        payload={"name": role.name},
    )
    caps_by_role = await svc.capabilities_by_role()
    return _role_out(role, caps_by_role.get(key, []))


@router.put("/roles/{key}/capabilities", response_model=RoleOut)
async def set_capabilities(
    key: str,
    payload: RoleCapabilitiesUpdate,
    request: Request,
    user: AuthenticatedUser = Depends(require_admin),
    settings: Settings = Depends(get_settings),
    session: AsyncSession = Depends(get_session),
) -> RoleOut:
    svc = RbacService(session)
    caps = [Capability(c) for c in payload.capabilities]
    try:
        role = await svc.set_capabilities(key, caps)
    except RoleNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "role_not_found") from exc
    except RoleImmutableError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, "role_not_editable") from exc
    await _emit(
        session,
        settings,
        request,
        user,
        action="rbac_capabilities_set",
        role_key=key,
        payload={"capabilities": sorted(payload.capabilities)},
    )
    return _role_out(role, payload.capabilities)


@router.delete("/roles/{key}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_role(
    key: str,
    request: Request,
    user: AuthenticatedUser = Depends(require_admin),
    settings: Settings = Depends(get_settings),
    session: AsyncSession = Depends(get_session),
) -> None:
    svc = RbacService(session)
    try:
        await svc.delete_role(key)
    except RoleNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "role_not_found") from exc
    except RoleImmutableError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, "system_role_not_deletable") from exc
    await _emit(
        session,
        settings,
        request,
        user,
        action="rbac_role_deleted",
        role_key=key,
        payload={},
    )


async def _lookup(svc: RbacService, key: str) -> Role:
    role = await svc.get_role(key)
    if role is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "role_not_found")
    return role


__all__ = ["router"]
