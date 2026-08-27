"""GroupTemplateService: CRUD + audit for AD group templates (Zielrollen)."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from magister_api.audit.service import AuditService
from magister_api.config import Settings
from magister_api.models.group_template import GroupTemplate
from magister_api.repositories.base import ScopeContext
from magister_api.repositories.group_templates import GroupTemplateRepository


class GroupTemplateNotFoundError(LookupError):
    pass


class GroupTemplateService:
    def __init__(self, session: AsyncSession, settings: Settings, scope: ScopeContext) -> None:
        self.session = session
        self.settings = settings
        self.scope = scope
        self.repo = GroupTemplateRepository(session)
        self.audit = AuditService(session, settings)

    async def list_all(self) -> tuple[list[GroupTemplate], dict[int, list[int]]]:
        rows = await self.repo.list_active()
        links = await self.repo.school_ids_for([r.id for r in rows])
        return rows, links

    async def list_for_school(
        self, school_id: int
    ) -> tuple[list[GroupTemplate], dict[int, list[int]]]:
        rows = await self.repo.list_for_school(school_id)
        links = await self.repo.school_ids_for([r.id for r in rows])
        return rows, links

    async def get(self, template_id: int) -> tuple[GroupTemplate, list[int]]:
        row = await self.repo.get(template_id)
        if row is None:
            raise GroupTemplateNotFoundError(str(template_id))
        links = await self.repo.school_ids_for([row.id])
        return row, links.get(row.id, [])

    async def create(
        self,
        *,
        name: str,
        description: str | None,
        kind: str | None,
        ad_groups: list[str],
        school_ids: list[int],
        ip: str | None,
        request_id: str,
    ) -> tuple[GroupTemplate, list[int]]:
        row = await self.repo.create(
            name=name,
            description=description,
            kind=kind,
            ad_groups=ad_groups,
            school_ids=school_ids,
        )
        await self.audit.emit(
            action="group_template_created",
            target_kind="group_template",
            target_id=str(row.id),
            actor_upn=self.scope.upn,
            actor_object_guid=self.scope.ad_object_guid,
            school_id=None,
            ip=ip,
            request_id=request_id,
            payload={
                "name": row.name,
                "group_count": len(row.ad_groups),
                "school_ids": list(school_ids),
            },
        )
        return row, list(dict.fromkeys(school_ids))

    async def update(
        self,
        *,
        template_id: int,
        name: str | None,
        description: str | None,
        kind: str | None,
        ad_groups: list[str] | None,
        school_ids: list[int] | None,
        ip: str | None,
        request_id: str,
    ) -> tuple[GroupTemplate, list[int]]:
        row, _ = await self.get(template_id)
        row = await self.repo.update(
            row,
            name=name,
            description=description,
            kind=kind,
            ad_groups=ad_groups,
            school_ids=school_ids,
        )
        links = await self.repo.school_ids_for([row.id])
        await self.audit.emit(
            action="group_template_updated",
            target_kind="group_template",
            target_id=str(row.id),
            actor_upn=self.scope.upn,
            actor_object_guid=self.scope.ad_object_guid,
            school_id=None,
            ip=ip,
            request_id=request_id,
            payload={"name": row.name, "group_count": len(row.ad_groups)},
        )
        return row, links.get(row.id, [])

    async def archive(self, *, template_id: int, ip: str | None, request_id: str) -> None:
        row, _ = await self.get(template_id)
        await self.repo.archive(row)
        await self.audit.emit(
            action="group_template_archived",
            target_kind="group_template",
            target_id=str(row.id),
            actor_upn=self.scope.upn,
            actor_object_guid=self.scope.ad_object_guid,
            school_id=None,
            ip=ip,
            request_id=request_id,
            payload={"name": row.name},
        )


__all__ = ["GroupTemplateNotFoundError", "GroupTemplateService"]
