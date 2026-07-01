"""``/schools`` — read-only listing for scope-aware dropdowns.

Admin sees every school; Schulleitung/SMI see only the schools in their
scope. Used by the class-creation form so an admin picks a school from a
dropdown instead of typing a numeric id.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from magister_api.auth.current_user import AuthenticatedUser
from magister_api.auth.rbac import require_schulleitung
from magister_api.db import get_session
from magister_api.repositories.schools import SchoolRepository
from magister_api.schemas.schools import SchoolOut

router = APIRouter(prefix="/schools", tags=["schools"])


@router.get("", response_model=list[SchoolOut])
async def list_schools(
    user: AuthenticatedUser = Depends(require_schulleitung),
    session: AsyncSession = Depends(get_session),
) -> list[SchoolOut]:
    rows = await SchoolRepository(session, user.to_scope()).list_in_scope()
    return [SchoolOut.model_validate(r) for r in rows]


__all__ = ["router"]
