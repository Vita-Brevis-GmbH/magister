"""ClassService: orchestrates ClassRepository + AuditService."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from magister_api.audit.service import AuditService
from magister_api.config import Settings
from magister_api.models.school_class import SchoolClass
from magister_api.repositories.base import ScopeContext
from magister_api.repositories.classes import ClassRepository


class ClassNotFoundError(LookupError):
    pass


class ClassPermissionError(PermissionError):
    """Raised on cross-school write attempts (Schulleitung A → School B)."""


class ClassService:
    def __init__(self, session: AsyncSession, settings: Settings, scope: ScopeContext) -> None:
        self.session = session
        self.settings = settings
        self.scope = scope
        self.repo = ClassRepository(session, scope)
        self.audit = AuditService(session, settings)

    async def list_active(self) -> list[SchoolClass]:
        return await self.repo.list_active()

    async def get(self, class_id: int) -> SchoolClass:
        row = await self.repo.get(class_id)
        if row is None:
            raise ClassNotFoundError(str(class_id))
        return row

    async def create(
        self,
        *,
        school_id: int,
        name: str,
        kuerzel: str | None,
        jahrgangsstufe: int,
        ip: str | None,
        request_id: str,
    ) -> SchoolClass:
        try:
            row = await self.repo.create(
                school_id=school_id,
                name=name,
                kuerzel=kuerzel,
                jahrgangsstufe=jahrgangsstufe,
            )
        except PermissionError as exc:
            raise ClassPermissionError("school_out_of_scope") from exc
        await self.audit.emit(
            action="class_created",
            target_kind="class",
            target_id=str(row.id),
            actor_upn=self.scope.upn,
            actor_object_guid=self.scope.ad_object_guid,
            school_id=row.school_id,
            ip=ip,
            request_id=request_id,
            payload={
                "name": row.name,
                "kuerzel": row.kuerzel,
                "jahrgangsstufe": row.jahrgangsstufe,
            },
        )
        return row

    async def rename(
        self,
        *,
        class_id: int,
        new_name: str | None,
        new_kuerzel: str | None,
        ip: str | None,
        request_id: str,
    ) -> SchoolClass:
        row = await self.get(class_id)
        old_name = row.name
        old_kuerzel = row.kuerzel
        row, name_changed = await self.repo.update(row, name=new_name, kuerzel=new_kuerzel)
        if name_changed or (new_kuerzel is not None and new_kuerzel != old_kuerzel):
            await self.audit.emit(
                action="class_renamed",
                target_kind="class",
                target_id=str(row.id),
                actor_upn=self.scope.upn,
                actor_object_guid=self.scope.ad_object_guid,
                school_id=row.school_id,
                ip=ip,
                request_id=request_id,
                payload={
                    "old_name": old_name,
                    "new_name": row.name,
                    "old_kuerzel": old_kuerzel,
                    "new_kuerzel": row.kuerzel,
                },
            )
        return row

    async def archive(
        self,
        *,
        class_id: int,
        ip: str | None,
        request_id: str,
    ) -> SchoolClass:
        row = await self.get(class_id)
        row = await self.repo.archive(row)
        await self.audit.emit(
            action="class_archived",
            target_kind="class",
            target_id=str(row.id),
            actor_upn=self.scope.upn,
            actor_object_guid=self.scope.ad_object_guid,
            school_id=row.school_id,
            ip=ip,
            request_id=request_id,
            payload={"name": row.name, "jahrgangsstufe": row.jahrgangsstufe},
        )
        return row
