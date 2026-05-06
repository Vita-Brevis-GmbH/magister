"""Read-side AD user service — listing with Schul-Scope + filter + pagination."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from magister_api.config import Settings
from magister_api.models.auth import AdUserCache
from magister_api.repositories.ad_users import AdUserListingRepository
from magister_api.repositories.base import ScopeContext


@dataclass(frozen=True)
class AdUserListing:
    rows: list[AdUserCache]
    total: int
    last_sync_at: datetime | None


class AdUsersService:
    def __init__(self, session: AsyncSession, settings: Settings, scope: ScopeContext) -> None:
        self.session = session
        self.settings = settings
        self.scope = scope
        self.repo = AdUserListingRepository(session, scope)

    async def list(
        self,
        *,
        kind: str | None,
        enabled: bool | None,
        search: str | None,
        class_id: int | None,
        offset: int,
        limit: int,
    ) -> AdUserListing:
        rows, total = await self.repo.list_filtered(
            kind=kind,
            enabled=enabled,
            search=search,
            class_id=class_id,
            offset=offset,
            limit=limit,
        )
        last_sync = await self.repo.latest_sync_for_scope()
        return AdUserListing(rows=rows, total=total, last_sync_at=last_sync)
