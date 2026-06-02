"""LetterService: render parent letters as PDFs (M3 US-1).

Renders Jinja2 HTML templates with school + student context, runs them
through WeasyPrint, returns the PDF bytes.

Templates:
- ``enrollment`` — Klassen-Eintritt (Anmeldung)
- ``class_change`` — Klassenwechsel
- ``password_handout`` — Passwort-Übergabe (an Eltern; nach Reset)

The temporary password for ``password_handout`` is NOT stored — the
caller must pass it in (typically the Schulleitung opens the letter
right after running a manual reset and copies the password into the
form before printing).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from weasyprint import HTML

from magister_api.audit.service import AuditService
from magister_api.config import Settings
from magister_api.letters.translations import LETTER_STRINGS_DE
from magister_api.models.auth import AdUserCache
from magister_api.models.class_membership import ClassMembership
from magister_api.models.class_teacher_role import (
    KL_ROLE_HAUPT,
    ClassTeacherRole,
)
from magister_api.models.school import School
from magister_api.models.school_class import SchoolClass
from magister_api.repositories.base import ScopeContext

TEMPLATE_ENROLLMENT = "enrollment"
TEMPLATE_CLASS_CHANGE = "class_change"
TEMPLATE_PASSWORD = "password_handout"  # noqa: S105 — template id, not a credential
ALLOWED_TEMPLATES: frozenset[str] = frozenset(
    {TEMPLATE_ENROLLMENT, TEMPLATE_CLASS_CHANGE, TEMPLATE_PASSWORD}
)


_TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "letters" / "templates"


class StudentNotFoundError(LookupError):
    pass


class StudentNotInScopeError(LookupError):
    pass


class UnknownTemplateError(ValueError):
    pass


class MissingTemplateInputError(ValueError):
    pass


@dataclass(frozen=True)
class LetterContext:
    """Optional caller-supplied extras for a specific template."""

    school_year: str | None = None
    first_day: str | None = None
    old_class_name: str | None = None
    effective_date: str | None = None
    temp_password: str | None = None


def _build_env() -> Environment:
    return Environment(
        loader=FileSystemLoader(str(_TEMPLATES_DIR)),
        autoescape=select_autoescape(["html", "xml"]),
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
    )


# Workaround: Jinja's str.format() filter would require a custom filter for
# named placeholders. Add a tiny "format" filter that calls .format(**kwargs).
def _format_filter(template: str, **kwargs: object) -> str:
    return template.format(**kwargs)


class LetterService:
    def __init__(self, session: AsyncSession, settings: Settings, scope: ScopeContext) -> None:
        self.session = session
        self.settings = settings
        self.scope = scope
        self.audit = AuditService(session, settings)
        self.env = _build_env()
        self.env.filters["format"] = _format_filter
        self.base_css = (_TEMPLATES_DIR / "_base.css").read_text(encoding="utf-8")

    async def prepare(
        self,
        *,
        template: str,
        student_guid: str,
        ctx: LetterContext,
        ip: str | None,
        request_id: str,
    ) -> str:
        """Look up student/school/class, validate inputs, audit, and return
        the rendered HTML. The caller renders the PDF in a threadpool.
        """
        if template not in ALLOWED_TEMPLATES:
            raise UnknownTemplateError(template)

        student = await self.session.get(AdUserCache, student_guid)
        if student is None or student.kind != "student":
            raise StudentNotFoundError(student_guid)

        # Scope check: non-admin callers must have the student's school in scope.
        if not self.scope.is_admin and (
            student.school_id is None or student.school_id not in self.scope.school_scope
        ):
            raise StudentNotInScopeError(student_guid)

        school = None
        if student.school_id is not None:
            school = await self.session.get(School, student.school_id)

        active_class = await self._active_class(student.ad_object_guid)
        kl_name = await self._haupt_kl_name(active_class.id) if active_class is not None else None

        self._require_inputs(template, ctx, has_class=active_class is not None)

        rendered_html = self._render_html(
            template=template,
            student=student,
            school=school,
            active_class=active_class,
            kl_name=kl_name,
            ctx=ctx,
        )

        await self.audit.emit(
            action="letter_generated",
            target_kind="user",
            target_id=student.ad_object_guid,
            actor_upn=self.scope.upn,
            actor_object_guid=self.scope.ad_object_guid,
            school_id=student.school_id,
            ip=ip,
            request_id=request_id,
            payload={
                "template": template,
                "student_upn": student.upn,
                "class_id": active_class.id if active_class else None,
            },
        )
        return rendered_html

    @staticmethod
    def html_to_pdf(html: str) -> bytes:
        """Pure-sync PDF render. Call via ``run_in_threadpool``."""
        pdf_bytes = HTML(string=html, base_url=str(_TEMPLATES_DIR)).write_pdf()
        if pdf_bytes is None:
            raise RuntimeError("WeasyPrint returned no PDF bytes")
        return pdf_bytes

    # ----- Helpers ------------------------------------------------------

    def _require_inputs(self, template: str, ctx: LetterContext, *, has_class: bool) -> None:
        if template in (TEMPLATE_ENROLLMENT, TEMPLATE_CLASS_CHANGE) and not has_class:
            raise MissingTemplateInputError("student has no active class")
        if template == TEMPLATE_ENROLLMENT:
            if not ctx.school_year or not ctx.first_day:
                raise MissingTemplateInputError("school_year and first_day are required")
        if template == TEMPLATE_CLASS_CHANGE:
            if not ctx.old_class_name or not ctx.effective_date:
                raise MissingTemplateInputError("old_class_name and effective_date are required")
        if template == TEMPLATE_PASSWORD:
            if not ctx.temp_password:
                raise MissingTemplateInputError("temp_password is required")

    async def _active_class(self, ad_object_guid: str) -> SchoolClass | None:
        from magister_api.models.base import utcnow

        now = utcnow()
        stmt = (
            select(SchoolClass)
            .join(ClassMembership, ClassMembership.class_id == SchoolClass.id)
            .where(ClassMembership.ad_object_guid == ad_object_guid)
            .where(ClassMembership.valid_from <= now)
            .where((ClassMembership.valid_to.is_(None)) | (ClassMembership.valid_to > now))
            .order_by(ClassMembership.valid_from.desc())
            .limit(1)
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def _haupt_kl_name(self, class_id: int) -> str | None:
        from magister_api.models.base import utcnow

        now = utcnow()
        stmt = (
            select(ClassTeacherRole, AdUserCache)
            .join(
                AdUserCache,
                AdUserCache.ad_object_guid == ClassTeacherRole.ad_object_guid,
            )
            .where(ClassTeacherRole.class_id == class_id)
            .where(ClassTeacherRole.role == KL_ROLE_HAUPT)
            .where(ClassTeacherRole.valid_from <= now)
            .where((ClassTeacherRole.valid_to.is_(None)) | (ClassTeacherRole.valid_to > now))
            .order_by(ClassTeacherRole.valid_from.desc())
            .limit(1)
        )
        row = (await self.session.execute(stmt)).first()
        if row is None:
            return None
        _, kl = row
        return kl.display_name or kl.upn

    def _render_html(
        self,
        *,
        template: str,
        student: AdUserCache,
        school: School | None,
        active_class: SchoolClass | None,
        kl_name: str | None,
        ctx: LetterContext,
    ) -> str:
        strings = LETTER_STRINGS_DE
        subject = strings[template]["subject"].format(
            class_name=(active_class.name if active_class else ""),
        )
        salutation = strings[template]["salutation"]

        school_data: dict[str, Any]
        if school is None:
            school_data = {"name": "", "locality": "", "address_line": "", "contact": ""}
        else:
            school_data = {
                "name": school.name,
                "locality": getattr(school, "locality", "") or "",
                "address_line": getattr(school, "address_line", "") or "",
                "contact": getattr(school, "contact", "") or "",
            }

        recipient_lines: list[str] = []
        if student.display_name:
            recipient_lines.append(student.display_name)
        if student.street_address:
            recipient_lines.append(student.street_address)
        if student.postal_code or student.locality:
            recipient_lines.append(f"{student.postal_code or ''} {student.locality or ''}".strip())

        template_ctx = {
            "lang": "de",
            "base_css": self.base_css,
            "subject": subject,
            "salutation": salutation,
            "school": school_data,
            "today": date.today().strftime("%d.%m.%Y"),
            "recipient": recipient_lines or None,
            "signed_by": self.scope.upn or "Die Schulleitung",
            "student": {
                "display_name": student.display_name or student.upn,
                "upn": student.upn,
            },
            "class_": (
                {"name": active_class.name, "id": active_class.id}
                if active_class
                else {"name": "", "id": None}
            ),
            "class_teacher": kl_name,
            "school_year": ctx.school_year,
            "first_day": ctx.first_day,
            "old_class_name": ctx.old_class_name,
            "effective_date": ctx.effective_date,
            "temp_password": ctx.temp_password,
            "t": strings,
        }
        return self.env.get_template(f"{template}.html").render(**template_ctx)


__all__ = [
    "ALLOWED_TEMPLATES",
    "LetterContext",
    "LetterService",
    "MissingTemplateInputError",
    "StudentNotFoundError",
    "StudentNotInScopeError",
    "TEMPLATE_CLASS_CHANGE",
    "TEMPLATE_ENROLLMENT",
    "TEMPLATE_PASSWORD",
    "UnknownTemplateError",
]
