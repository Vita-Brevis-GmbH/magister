"""Repository for the AD group catalog (``ad_group_cache``).

The catalog is AD-global (not personal data), so neither the read nor the write
side is school-scoped. The sync writer upserts by ``objectGUID``; the read side
lists groups for the Userkonfiguration checkbox-picker.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from magister_api.ad.client import AdGroupRecord
from magister_api.models.ad_group import AdGroupCache
from magister_api.models.base import utcnow


class AdGroupCatalogRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_all(self) -> list[AdGroupCache]:
        """Return the whole catalog, ordered by CN (case-insensitive)."""
        stmt = select(AdGroupCache).order_by(AdGroupCache.cn)
        return list((await self.session.execute(stmt)).scalars().all())

    async def upsert_from_ad(self, records: Sequence[AdGroupRecord]) -> int:
        """Upsert each group by ``objectGUID``. Returns the number of rows."""
        if not records:
            return 0
        now = utcnow()
        rows: list[dict[str, Any]] = [
            {
                "ad_object_guid": r.ad_object_guid,
                "distinguished_name": r.distinguished_name,
                "cn": r.cn,
                "sam_account_name": r.sam_account_name,
                "description": r.description,
                "last_sync_at": now,
            }
            for r in records
        ]
        excluded = pg_insert(AdGroupCache).excluded
        stmt = (
            pg_insert(AdGroupCache)
            .values(rows)
            .on_conflict_do_update(
                index_elements=[AdGroupCache.ad_object_guid],
                set_={
                    "distinguished_name": excluded.distinguished_name,
                    "cn": excluded.cn,
                    "sam_account_name": excluded.sam_account_name,
                    "description": excluded.description,
                    "last_sync_at": now,
                },
            )
        )
        await self.session.execute(stmt)
        await self.session.flush()
        return len(rows)


__all__ = ["AdGroupCatalogRepository"]
