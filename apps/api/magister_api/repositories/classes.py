"""SchoolClass repository — all reads/writes are school-scope filtered."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from magister_api.cache import bump_kind, cache_key_for_scope, get_cache
from magister_api.models.school_class import (
    CLASS_STATUS_ACTIVE,
    CLASS_STATUS_ARCHIVED,
    SchoolClass,
)
from magister_api.repositories.base import BaseRepository, ScopeContext

CACHE_KIND = "classes_active"
CACHE_TTL_S = 30.0


class ClassRepository(BaseRepository):
    def __init__(self, session: AsyncSession, scope: ScopeContext) -> None:
        super().__init__(session, scope)

    async def list_active(self) -> list[SchoolClass]:
        cache = get_cache()
        scope_ids = None if self.scope.is_admin else self.scope.school_scope
        key = cache_key_for_scope(CACHE_KIND, scope_ids)
        cached = cache.get(key)
        if cached is not None:
            return list(cached)
        stmt = self.apply_scope(
            select(SchoolClass).where(SchoolClass.status == CLASS_STATUS_ACTIVE),
            SchoolClass.school_id,
        ).order_by(SchoolClass.school_id, SchoolClass.jahrgangsstufe, SchoolClass.name)
        rows = list((await self.session.execute(stmt)).scalars().all())
        cache.set(key, rows, ttl_s=CACHE_TTL_S)
        return rows

    async def get(self, class_id: int) -> SchoolClass | None:
        stmt = self.apply_scope(
            select(SchoolClass).where(SchoolClass.id == class_id),
            SchoolClass.school_id,
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def create(
        self,
        *,
        school_id: int,
        name: str,
        kuerzel: str | None,
        jahrgangsstufe: int,
        jahrgangsstufe_bis: int | None = None,
        details: str | None = None,
    ) -> SchoolClass:
        if not self.scope.can_access_school(school_id):
            raise PermissionError("school_out_of_scope")
        row = SchoolClass(
            school_id=school_id,
            name=name,
            kuerzel=kuerzel,
            jahrgangsstufe=jahrgangsstufe,
            jahrgangsstufe_bis=jahrgangsstufe_bis,
            details=details,
            status=CLASS_STATUS_ACTIVE,
        )
        self.session.add(row)
        await self.session.flush()
        bump_kind(CACHE_KIND)
        return row

    async def update(
        self,
        cls: SchoolClass,
        *,
        name: str | None = None,
        kuerzel: str | None = None,
        details: str | None = None,
        jahrgangsstufe: int | None = None,
        set_jahrgangsstufe_bis: bool = False,
        jahrgangsstufe_bis: int | None = None,
    ) -> tuple[SchoolClass, bool]:
        """Apply provided fields. Returns (row, cache_relevant_changed).

        The active-classes cache stores name + grade (used for sorting/display),
        so a name or grade change bumps it; kuerzel and details do not. For the
        optional upper bound, ``set_jahrgangsstufe_bis`` distinguishes "clear to
        single-grade" (True + None) from "leave unchanged" (False).
        """
        cache_relevant_changed = False
        if name is not None and name != cls.name:
            cls.name = name
            cache_relevant_changed = True
        if kuerzel is not None and kuerzel != cls.kuerzel:
            cls.kuerzel = kuerzel
        if details is not None and details != cls.details:
            cls.details = details
        if jahrgangsstufe is not None and jahrgangsstufe != cls.jahrgangsstufe:
            cls.jahrgangsstufe = jahrgangsstufe
            cache_relevant_changed = True
        if set_jahrgangsstufe_bis and jahrgangsstufe_bis != cls.jahrgangsstufe_bis:
            cls.jahrgangsstufe_bis = jahrgangsstufe_bis
            cache_relevant_changed = True
        await self.session.flush()
        if cache_relevant_changed:
            bump_kind(CACHE_KIND)
        return cls, cache_relevant_changed

    async def archive(self, cls: SchoolClass) -> SchoolClass:
        cls.status = CLASS_STATUS_ARCHIVED
        await self.session.flush()
        bump_kind(CACHE_KIND)
        return cls
