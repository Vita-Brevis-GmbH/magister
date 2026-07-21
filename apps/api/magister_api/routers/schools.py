"""``/schools`` router.

- GET  /schools        — scope-aware listing (Schulleitung/SMI see their
  schools, Admin sees all). Used by dropdowns and the read view.
- GET  /schools/{id}   — single school within scope.
- POST /schools        — create (Admin only).
- PATCH /schools/{id}  — edit address/contact/etc. (Admin only).
- DELETE /schools/{id} — remove a school with no classes (Admin only).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from magister_api.auth.current_user import AuthenticatedUser
from magister_api.auth.rbac import require_admin, require_schulleitung
from magister_api.config import Settings, get_settings
from magister_api.db import get_session
from magister_api.repositories.schools import SchoolRepository
from magister_api.routers._helpers import _ip_request_id
from magister_api.schemas.schools import SchoolCreate, SchoolOut, SchoolUpdate
from magister_api.services.schools import (
    SchoolInUseError,
    SchoolKuerzelConflictError,
    SchoolNotFoundError,
    SchoolService,
)

router = APIRouter(prefix="/schools", tags=["schools"])


@router.get("", response_model=list[SchoolOut])
async def list_schools(
    user: AuthenticatedUser = Depends(require_schulleitung),
    session: AsyncSession = Depends(get_session),
) -> list[SchoolOut]:
    rows = await SchoolRepository(session, user.to_scope()).list_in_scope()
    return [SchoolOut.model_validate(r) for r in rows]


@router.get("/{school_id}", response_model=SchoolOut)
async def get_school(
    school_id: int,
    user: AuthenticatedUser = Depends(require_schulleitung),
    session: AsyncSession = Depends(get_session),
) -> SchoolOut:
    row = await SchoolRepository(session, user.to_scope()).get_in_scope(school_id)
    if row is None:
        raise HTTPException(status_code=404, detail="school_not_found")
    return SchoolOut.model_validate(row)


@router.post("", response_model=SchoolOut, status_code=status.HTTP_201_CREATED)
async def create_school(
    payload: SchoolCreate,
    request: Request,
    user: AuthenticatedUser = Depends(require_admin),
    settings: Settings = Depends(get_settings),
    session: AsyncSession = Depends(get_session),
) -> SchoolOut:
    svc = SchoolService(session, settings, user.to_scope())
    ip, request_id = _ip_request_id(request)
    try:
        # exclude_none so the optional AD-config group lists (default None) fall
        # back to the model's server_default `[]` instead of hitting NOT NULL.
        row = await svc.create(
            fields=payload.model_dump(exclude_none=True), ip=ip, request_id=request_id
        )
    except SchoolKuerzelConflictError as exc:
        raise HTTPException(status_code=409, detail="kuerzel_conflict") from exc
    return SchoolOut.model_validate(row)


@router.patch("/{school_id}", response_model=SchoolOut)
async def patch_school(
    school_id: int,
    payload: SchoolUpdate,
    request: Request,
    user: AuthenticatedUser = Depends(require_admin),
    settings: Settings = Depends(get_settings),
    session: AsyncSession = Depends(get_session),
) -> SchoolOut:
    svc = SchoolService(session, settings, user.to_scope())
    ip, request_id = _ip_request_id(request)
    changes = payload.model_dump(exclude_unset=True)
    try:
        row = await svc.update(school_id=school_id, changes=changes, ip=ip, request_id=request_id)
    except SchoolNotFoundError as exc:
        raise HTTPException(status_code=404, detail="school_not_found") from exc
    except SchoolKuerzelConflictError as exc:
        raise HTTPException(status_code=409, detail="kuerzel_conflict") from exc
    return SchoolOut.model_validate(row)


@router.delete("/{school_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_school(
    school_id: int,
    request: Request,
    user: AuthenticatedUser = Depends(require_admin),
    settings: Settings = Depends(get_settings),
    session: AsyncSession = Depends(get_session),
) -> None:
    svc = SchoolService(session, settings, user.to_scope())
    ip, request_id = _ip_request_id(request)
    try:
        await svc.delete(school_id=school_id, ip=ip, request_id=request_id)
    except SchoolNotFoundError as exc:
        raise HTTPException(status_code=404, detail="school_not_found") from exc
    except SchoolInUseError as exc:
        raise HTTPException(status_code=409, detail="school_in_use") from exc
    return None


__all__ = ["router"]
