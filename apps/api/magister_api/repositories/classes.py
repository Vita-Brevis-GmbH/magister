"""SchoolClass repository — all reads/writes are school-scope filtered."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from magister_api.models.school_class import (
    CLASS_STATUS_ACTIVE,
    CLASS_STATUS_ARCHIVED,
    SchoolClass,
)
from magister_api.repositories.base import BaseRepository, ScopeContext


class ClassRepository(BaseRepository):
    def __init__(self, session: AsyncSession, scope: ScopeContext) -> None:
        super().__init__(session, scope)

    async def list_active(self) -> list[SchoolClass]:
        stmt = self.apply_scope(
            select(SchoolClass).where(SchoolClass.status == CLASS_STATUS_ACTIVE),
            SchoolClass.school_id,
        ).order_by(SchoolClass.school_id, SchoolClass.jahrgangsstufe, SchoolClass.name)
        return list((await self.session.execute(stmt)).scalars().all())

    async def get(self, class_id: int) -> SchoolClass | None:
        stmt = self.apply_scope(
            select(SchoolClass).where(SchoolClass.id == class_id),
            SchoolClass.school_id,
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def create(
        self, *, school_id: int, name: str, kuerzel: str | None, jahrgangsstufe: int
    ) -> SchoolClass:
        if not self.scope.can_access_school(school_id):
            raise PermissionError("school_out_of_scope")
        row = SchoolClass(
            school_id=school_id,
            name=name,
            kuerzel=kuerzel,
            jahrgangsstufe=jahrgangsstufe,
            status=CLASS_STATUS_ACTIVE,
        )
        self.session.add(row)
        await self.session.flush()
        return row

    async def update(
        self,
        cls: SchoolClass,
        *,
        name: str | None = None,
        kuerzel: str | None = None,
    ) -> tuple[SchoolClass, bool]:
        """Apply non-None fields. Returns (row, name_changed)."""
        name_changed = False
        if name is not None and name != cls.name:
            cls.name = name
            name_changed = True
        if kuerzel is not None and kuerzel != cls.kuerzel:
            cls.kuerzel = kuerzel
        await self.session.flush()
        return cls, name_changed

    async def archive(self, cls: SchoolClass) -> SchoolClass:
        cls.status = CLASS_STATUS_ARCHIVED
        await self.session.flush()
        return cls
