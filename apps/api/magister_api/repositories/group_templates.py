"""GroupTemplate repository.

Group templates are AD-global config (not personenbezogen), so — like the AD
group catalog — the rows are not school-scoped; access is gated at the router
(``require_manage``). The M2M ``group_template_schools`` only *filters* which
templates are offered per Standort.
"""

from __future__ import annotations

from sqlalchemy import delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from magister_api.ad.password import password_stays
from magister_api.models.group_template import (
    FIXED_KINDS,
    GROUP_TEMPLATE_STATUS_ACTIVE,
    GROUP_TEMPLATE_STATUS_ARCHIVED,
    GroupTemplate,
    GroupTemplateSchool,
)

#: Anlage-Vorgaben einer Zielgruppe, die Create/Update durchreichen.
OPTION_FIELDS: frozenset[str] = frozenset(
    {
        "password_profile",
        "force_change",
        "cannot_change_password",
        "password_never_expires",
        "store_password",
        "ad_ou",
    }
)


def _normalize(row: GroupTemplate, *, has_links: bool) -> None:
    """Was sich widerspricht, wird beim Speichern gerade gezogen.

    * Ziel-OU bei freier Kontoart oder ohne Standort (dort ist sie die OU für
      Konten, die ohne Standort angelegt werden); bei fester Kontoart mit
      Standorten legt deren OU fest. "" heisst entfernen.
    * "Im Tresor ablegen" nur, wenn das Passwort so bleibt (keine erzwungene
      Änderung, kann nicht ändern, läuft nie ab) — sonst gäbe die Klassen-
      Passwortliste bald ein falsches Passwort aus.
    """
    if not row.ad_ou or (row.kind in FIXED_KINDS and has_links):
        row.ad_ou = None
    if row.store_password and not password_stays(
        force_change=row.force_change,
        cannot_change_password=row.cannot_change_password,
        password_never_expires=row.password_never_expires,
    ):
        row.store_password = False


class GroupTemplateRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_active(self) -> list[GroupTemplate]:
        stmt = (
            select(GroupTemplate)
            .where(GroupTemplate.status == GROUP_TEMPLATE_STATUS_ACTIVE)
            .order_by(GroupTemplate.name)
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def list_for_school(self, school_id: int) -> list[GroupTemplate]:
        """Active templates offered at ``school_id`` — either linked to it, or
        global (no Standort links at all)."""
        link = GroupTemplateSchool
        has_any = (
            select(link.group_template_id)
            .where(link.group_template_id == GroupTemplate.id)
            .exists()
        )
        linked_here = (
            select(link.group_template_id)
            .where(link.group_template_id == GroupTemplate.id)
            .where(link.school_id == school_id)
            .exists()
        )
        stmt = (
            select(GroupTemplate)
            .where(GroupTemplate.status == GROUP_TEMPLATE_STATUS_ACTIVE)
            .where(or_(~has_any, linked_here))
            .order_by(GroupTemplate.name)
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def get(self, template_id: int) -> GroupTemplate | None:
        return await self.session.get(GroupTemplate, template_id)

    async def school_ids_for(self, template_ids: list[int]) -> dict[int, list[int]]:
        """Map each template id → its linked Standort ids (empty list = global)."""
        if not template_ids:
            return {}
        stmt = select(GroupTemplateSchool.group_template_id, GroupTemplateSchool.school_id).where(
            GroupTemplateSchool.group_template_id.in_(template_ids)
        )
        out: dict[int, list[int]] = {tid: [] for tid in template_ids}
        for tid, sid in (await self.session.execute(stmt)).all():
            out.setdefault(tid, []).append(sid)
        return out

    async def create(
        self,
        *,
        name: str,
        description: str | None,
        kind: str | None,
        ad_groups: list[str],
        school_ids: list[int],
        options: dict[str, object] | None = None,
    ) -> GroupTemplate:
        row = GroupTemplate(
            name=name,
            description=description,
            kind=kind,
            ad_groups=list(ad_groups),
            status=GROUP_TEMPLATE_STATUS_ACTIVE,
            **(options or {}),
        )
        _normalize(row, has_links=bool(school_ids))
        self.session.add(row)
        await self.session.flush()
        await self._set_links(row.id, school_ids)
        return row

    async def update(
        self,
        row: GroupTemplate,
        *,
        name: str | None = None,
        description: str | None = None,
        kind: str | None = None,
        ad_groups: list[str] | None = None,
        school_ids: list[int] | None = None,
        options: dict[str, object] | None = None,
    ) -> GroupTemplate:
        for key, value in (options or {}).items():
            if key in OPTION_FIELDS and value is not None:
                setattr(row, key, value)
        if name is not None:
            row.name = name
        if description is not None:
            row.description = description
        if kind is not None:
            row.kind = kind
        if ad_groups is not None:
            row.ad_groups = list(ad_groups)
        if school_ids is None:
            has_links = bool((await self.school_ids_for([row.id])).get(row.id))
        else:
            has_links = bool(school_ids)
        _normalize(row, has_links=has_links)
        await self.session.flush()
        if school_ids is not None:
            await self._set_links(row.id, school_ids)
        return row

    async def archive(self, row: GroupTemplate) -> GroupTemplate:
        row.status = GROUP_TEMPLATE_STATUS_ARCHIVED
        await self.session.flush()
        return row

    async def _set_links(self, template_id: int, school_ids: list[int]) -> None:
        await self.session.execute(
            delete(GroupTemplateSchool).where(GroupTemplateSchool.group_template_id == template_id)
        )
        seen: set[int] = set()
        for sid in school_ids:
            if sid in seen:
                continue
            seen.add(sid)
            self.session.add(GroupTemplateSchool(group_template_id=template_id, school_id=sid))
        await self.session.flush()
