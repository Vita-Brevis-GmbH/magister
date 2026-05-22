"""Helper to enrich GUID-keyed rows with display-name fields from ad_user_cache.

Used by the class-teachers and class-memberships routers so the SPA can
render a friendly label without making a second ``/users`` call (which
KL-level callers can't access). One round-trip per response, regardless
of how many rows are being enriched.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import TypeVar

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from magister_api.models.auth import AdUserCache

T = TypeVar("T")


async def fetch_user_labels(
    session: AsyncSession,
    guids: Iterable[str],
) -> dict[str, AdUserCache]:
    """Return ``{ad_object_guid: AdUserCache}`` for the given guids.

    # scope-bypass: the caller is already scope-checked at the class level
    # (require_class_writer / require_schulleitung); this look-up is only
    # there to add a display label and never widens visibility.
    """
    guid_list = list({g for g in guids if g})
    if not guid_list:
        return {}
    stmt = select(AdUserCache).where(AdUserCache.ad_object_guid.in_(guid_list))
    result = await session.execute(stmt)
    return {row.ad_object_guid: row for row in result.scalars().all()}


__all__ = ["fetch_user_labels"]
