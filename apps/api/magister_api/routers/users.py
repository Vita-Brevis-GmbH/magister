"""``/users`` — read-only listing of cached AD users (KL + Schulleitung + Admin)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from magister_api.auth.current_user import AuthenticatedUser
from magister_api.auth.rbac import require_role
from magister_api.config import Settings, get_settings
from magister_api.db import get_session
from magister_api.schemas.ad_users import AdUserListResponse, AdUserOut
from magister_api.services.ad_users import AdUsersService

router = APIRouter(prefix="/users", tags=["users"])


# KL-as-actor permission lands in #6 (kl_perm helper exists already in services.class_teachers).
# Until then, listing is open to Schulleitung-or-above; KL access is enabled in the next PR.
require_listing = require_role("schulleitung")


@router.get("", response_model=AdUserListResponse)
async def list_users(
    user: AuthenticatedUser = Depends(require_listing),
    settings: Settings = Depends(get_settings),
    session: AsyncSession = Depends(get_session),
    kind: Annotated[
        str | None,
        Query(description="Filter by 'teacher' | 'student' | 'admin'."),
    ] = None,
    enabled: Annotated[bool | None, Query(description="Filter by AD enabled-flag.")] = None,
    search: Annotated[
        str | None,
        Query(min_length=1, max_length=64, description="Substring on UPN/given_name/surname."),
    ] = None,
    class_id: Annotated[
        int | None,
        Query(description="Filter to teachers with active KL role for this class."),
    ] = None,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> AdUserListResponse:
    svc = AdUsersService(session, settings, user.to_scope())
    listing = await svc.list(
        kind=kind,
        enabled=enabled,
        search=search,
        class_id=class_id,
        offset=offset,
        limit=limit,
    )
    return AdUserListResponse(
        items=[AdUserOut.model_validate(r) for r in listing.rows],
        total=listing.total,
        offset=offset,
        limit=limit,
        last_sync_at=listing.last_sync_at,
    )


__all__ = ["router"]
