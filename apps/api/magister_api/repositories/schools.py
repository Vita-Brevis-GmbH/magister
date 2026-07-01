"""School repository — listing scoped to the caller's school access.

Schools are the scope entity themselves, so the scope filter runs against
``School.id`` directly (admin sees all; everyone else only their scope).
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from magister_api.models.school import School
from magister_api.repositories.base import BaseRepository, ScopeContext


class SchoolRepository(BaseRepository):
    def __init__(self, session: AsyncSession, scope: ScopeContext) -> None:
        super().__init__(session, scope)

    async def list_in_scope(self) -> list[School]:
        stmt = self.apply_scope(select(School), School.id).order_by(School.name)
        return list((await self.session.execute(stmt)).scalars().all())


__all__ = ["SchoolRepository"]
