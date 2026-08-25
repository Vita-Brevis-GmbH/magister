"""Document-template repository (M6 Feature B).

Templates are operator configuration, not personal data, so no ``school_id``
scope filter applies here — a template can be global (``school_id`` NULL) or
scoped to one school, and the admin surface manages both. Which school a
rendered document belongs to is decided at render time by :meth:`resolve`.
"""

from __future__ import annotations

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from magister_api.models.base import utcnow
from magister_api.models.document_template import DocumentTemplate


class DocumentTemplateRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def resolve(
        self, *, key: str, language: str, school_id: int | None
    ) -> DocumentTemplate | None:
        """Active template for a render: school-specific wins over global."""
        stmt = select(DocumentTemplate).where(
            DocumentTemplate.key == key,
            DocumentTemplate.language == language,
            DocumentTemplate.is_active.is_(True),
            or_(
                DocumentTemplate.school_id == school_id,
                DocumentTemplate.school_id.is_(None),
            ),
        )
        rows = list((await self.session.execute(stmt)).scalars().all())
        specific = [r for r in rows if r.school_id == school_id and school_id is not None]
        if specific:
            return specific[0]
        return next((r for r in rows if r.school_id is None), None)

    async def list_for_admin(self, *, school_id: int | None) -> list[DocumentTemplate]:
        """Global rows plus, when a school is given, that school's rows."""
        cond = (
            DocumentTemplate.school_id.is_(None)
            if school_id is None
            else or_(
                DocumentTemplate.school_id.is_(None),
                DocumentTemplate.school_id == school_id,
            )
        )
        stmt = (
            select(DocumentTemplate)
            .where(cond)
            .order_by(DocumentTemplate.key, DocumentTemplate.language, DocumentTemplate.school_id)
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def get(self, template_id: int) -> DocumentTemplate | None:
        return await self.session.get(DocumentTemplate, template_id)

    async def get_exact(
        self, *, key: str, language: str, school_id: int | None
    ) -> DocumentTemplate | None:
        stmt = select(DocumentTemplate).where(
            DocumentTemplate.key == key,
            DocumentTemplate.language == language,
            DocumentTemplate.school_id.is_(None)
            if school_id is None
            else DocumentTemplate.school_id == school_id,
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def upsert(
        self,
        *,
        key: str,
        language: str,
        school_id: int | None,
        subject: str | None,
        body_html: str,
        is_active: bool,
        updated_by: str | None,
    ) -> DocumentTemplate:
        row = await self.get_exact(key=key, language=language, school_id=school_id)
        if row is None:
            row = DocumentTemplate(key=key, language=language, school_id=school_id)
            self.session.add(row)
        row.subject = subject
        row.body_html = body_html
        row.is_active = is_active
        row.updated_by = updated_by
        row.updated_at = utcnow()
        await self.session.flush()
        return row

    async def delete(self, row: DocumentTemplate) -> None:
        await self.session.delete(row)
        await self.session.flush()
