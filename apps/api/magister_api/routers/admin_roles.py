"""Admin role-assignment management (admin / schulleitung / smi).

Gives an admin a single place to see who holds which elevated role and to
grant/revoke them — the piece that previously only existed via env-bootstrap
(admin) or direct SQL (schulleitung/smi). ``kl`` is out of scope here: it is
derived from class-teacher assignments (see class_teachers router).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from magister_api.audit.service import AuditService
from magister_api.auth.current_user import AuthenticatedUser
from magister_api.auth.rbac import require_admin
from magister_api.config import Settings, get_settings
from magister_api.db import get_session
from magister_api.models.auth import AdUserCache
from magister_api.models.school import School
from magister_api.repositories.auth import RoleAssignmentRepository
from magister_api.routers._helpers import _ip_request_id
from magister_api.schemas.roles import RoleAssignmentOut, RoleGrantRequest
from magister_api.services._user_enrich import fetch_user_labels, user_label_fields

router = APIRouter(prefix="/admin", tags=["admin"])


async def _school_names(session: AsyncSession) -> dict[int, str]:
    rows = (await session.execute(select(School.id, School.name))).all()
    return {r.id: r.name for r in rows}


@router.get("/roles", response_model=list[RoleAssignmentOut])
async def list_roles(
    user: AuthenticatedUser = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
) -> list[RoleAssignmentOut]:
    """Every active admin/schulleitung/smi grant, with holder + school labels."""
    rows = await RoleAssignmentRepository(session).list_all_active()
    labels = await fetch_user_labels(session, (r.ad_object_guid for r in rows))
    schools = await _school_names(session)
    return [
        RoleAssignmentOut(
            ad_object_guid=r.ad_object_guid,
            role=r.role,
            school_id=r.school_id,
            school_name=schools.get(r.school_id) if r.school_id is not None else None,
            granted_by=r.granted_by,
            granted_at=r.granted_at,
            **user_label_fields(labels.get(r.ad_object_guid)),
        )
        for r in rows
    ]


@router.post(
    "/users/{ad_object_guid}/roles",
    response_model=RoleAssignmentOut,
    status_code=status.HTTP_201_CREATED,
)
async def grant_role(
    ad_object_guid: str,
    payload: RoleGrantRequest,
    request: Request,
    user: AuthenticatedUser = Depends(require_admin),
    settings: Settings = Depends(get_settings),
    session: AsyncSession = Depends(get_session),
) -> RoleAssignmentOut:
    target = await session.get(AdUserCache, ad_object_guid)
    if target is None:
        raise HTTPException(status_code=404, detail="user_not_found")
    if payload.school_id is not None and await session.get(School, payload.school_id) is None:
        raise HTTPException(status_code=404, detail="school_not_found")

    repo = RoleAssignmentRepository(session)
    assignment = await repo.grant(
        ad_object_guid=ad_object_guid,
        role=payload.role,
        school_id=payload.school_id,
        granted_by=user.upn,
    )
    ip, request_id = _ip_request_id(request)
    await AuditService(session, settings).emit(
        action="role_granted",
        target_kind="role_assignment",
        target_id=ad_object_guid,
        actor_upn=user.upn,
        actor_object_guid=user.ad_object_guid,
        school_id=payload.school_id,
        ip=ip,
        request_id=request_id,
        payload={"role": payload.role, "school_id": payload.school_id, "via": "admin_ui"},
    )
    schools = await _school_names(session)
    return RoleAssignmentOut(
        ad_object_guid=ad_object_guid,
        role=payload.role,
        school_id=payload.school_id,
        school_name=schools.get(payload.school_id) if payload.school_id is not None else None,
        granted_by=assignment.granted_by,
        granted_at=assignment.granted_at,
        **user_label_fields(target),
    )


@router.delete("/users/{ad_object_guid}/roles", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_role(
    ad_object_guid: str,
    request: Request,
    role: str,
    school_id: int | None = None,
    user: AuthenticatedUser = Depends(require_admin),
    settings: Settings = Depends(get_settings),
    session: AsyncSession = Depends(get_session),
) -> None:
    # Reuse the grant validator to reject bad role/scope combinations.
    try:
        RoleGrantRequest(role=role, school_id=school_id)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail="invalid_role") from exc
    repo = RoleAssignmentRepository(session)
    revoked = await repo.revoke(
        ad_object_guid=ad_object_guid,
        role=role,
        school_id=school_id,
    )
    if revoked is None:
        raise HTTPException(status_code=404, detail="role_not_found")
    ip, request_id = _ip_request_id(request)
    await AuditService(session, settings).emit(
        action="role_revoked",
        target_kind="role_assignment",
        target_id=ad_object_guid,
        actor_upn=user.upn,
        actor_object_guid=user.ad_object_guid,
        school_id=school_id,
        ip=ip,
        request_id=request_id,
        payload={"role": role, "school_id": school_id, "via": "admin_ui"},
    )


__all__ = ["router"]
