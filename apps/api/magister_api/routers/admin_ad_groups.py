"""``/admin/ad-groups`` — the synced AD group catalog for the checkbox pickers.

Read-only. The catalog is AD-global (not per-school); the *selection* of default
group templates is per-school (edited on the school subpage).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from magister_api.auth.current_user import AuthenticatedUser
from magister_api.auth.rbac import require_manage
from magister_api.db import get_session
from magister_api.repositories.ad_groups import AdGroupCatalogRepository
from magister_api.schemas.ad_groups import AdGroupOut

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/ad-groups", response_model=list[AdGroupOut])
async def list_ad_groups(
    user: AuthenticatedUser = Depends(require_manage),
    session: AsyncSession = Depends(get_session),
) -> list[AdGroupOut]:
    rows = await AdGroupCatalogRepository(session).list_all()
    return [AdGroupOut.model_validate(r) for r in rows]


__all__ = ["router"]
