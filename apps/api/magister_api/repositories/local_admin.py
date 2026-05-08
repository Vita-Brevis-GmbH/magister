"""Repository for the singleton ``local_admins`` row."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from magister_api.models.local_admin import LocalAdmin


class LocalAdminRepository:
    """All access goes through ``id=1``; the table is a singleton.

    # scope-bypass: local admin is global (no school scope by definition).
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self) -> LocalAdmin | None:
        return await self.session.get(LocalAdmin, 1)

    async def get_by_username(self, username: str) -> LocalAdmin | None:
        stmt = select(LocalAdmin).where(LocalAdmin.username == username)
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def upsert(self, row: LocalAdmin) -> LocalAdmin:
        if row.id != 1:
            raise ValueError("LocalAdmin is a singleton with id=1")
        merged = await self.session.merge(row)
        await self.session.flush()
        return merged
