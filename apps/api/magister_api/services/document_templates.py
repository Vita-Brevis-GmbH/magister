"""Document-template service (M6 Feature B, ADR-0009 D2).

Operators can override the built-in letter templates with their own HTML +
subject per ``(key, language, school)``. Rendering goes through a Jinja2
**SandboxedEnvironment** so operator-authored templates cannot reach server
state — only the declared context is available. When no active override exists
the caller falls back to the built-in template, so default behaviour is
unchanged.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from jinja2 import StrictUndefined, TemplateError
from jinja2.sandbox import SandboxedEnvironment
from sqlalchemy.ext.asyncio import AsyncSession

from magister_api.audit.service import AuditService
from magister_api.config import Settings
from magister_api.models.document_template import DocumentTemplate
from magister_api.repositories.document_templates import DocumentTemplateRepository

# The letter templates an operator may override (mirrors letters.ALLOWED_TEMPLATES).
EDITABLE_KEYS: tuple[str, ...] = ("enrollment", "class_change", "password_handout")

# Placeholders available to every template body (for the editor's variable list).
PLACEHOLDERS: tuple[str, ...] = (
    "subject",
    "salutation",
    "today",
    "signed_by",
    "recipient",
    "school.name",
    "school.locality",
    "school.address_line",
    "school.contact",
    "student.display_name",
    "student.upn",
    "class_.name",
    "class_teacher",
    "school_year",
    "first_day",
    "old_class_name",
    "effective_date",
    "temp_password",
)


# Starter content per key — the "template for the template". The editor loads
# this as a sensible starting point so operators edit real text instead of a
# blank field. Self-contained HTML (wrapped in the print layout at render time);
# uses only the declared PLACEHOLDERS.
STARTER_TEMPLATES: dict[str, dict[str, str]] = {
    "enrollment": {
        "subject": "Eintritt in die Klasse {{ class_.name }}",
        "body_html": (
            "<h1>{{ subject }}</h1>\n"
            "<p>{{ salutation }}</p>\n"
            "<p>Wir freuen uns, {{ student.display_name }} in der Klasse "
            "<strong>{{ class_.name }}</strong> begrüssen zu dürfen. "
            "Der erste Schultag ist der {{ first_day }} (Schuljahr {{ school_year }}).</p>\n"
            "<p>Klassenlehrperson: {{ class_teacher }}.</p>\n"
            "<p>Freundliche Grüsse<br>{{ signed_by }}<br>{{ school.name }}</p>\n"
        ),
    },
    "class_change": {
        "subject": "Klassenwechsel von {{ old_class_name }} nach {{ class_.name }}",
        "body_html": (
            "<h1>{{ subject }}</h1>\n"
            "<p>{{ salutation }}</p>\n"
            "<p>{{ student.display_name }} wechselt per {{ effective_date }} von der Klasse "
            "{{ old_class_name }} in die Klasse <strong>{{ class_.name }}</strong>.</p>\n"
            "<p>Neue Klassenlehrperson: {{ class_teacher }}.</p>\n"
            "<p>Freundliche Grüsse<br>{{ signed_by }}<br>{{ school.name }}</p>\n"
        ),
    },
    "password_handout": {
        "subject": "Neue Zugangsdaten für {{ student.display_name }}",
        "body_html": (
            "<h1>{{ subject }}</h1>\n"
            "<p>{{ salutation }}</p>\n"
            "<p>Das Passwort für {{ student.display_name }} "
            "({{ student.upn }}) wurde neu gesetzt:</p>\n"
            '<p style="font-size:1.4em"><strong>{{ temp_password }}</strong></p>\n'
            "<p>Bitte das Passwort beim ersten Anmelden ändern und sicher aufbewahren.</p>\n"
            "<p>Freundliche Grüsse<br>{{ signed_by }}<br>{{ school.name }}</p>\n"
        ),
    },
}

# Company-edition starter variants for the same keys: same placeholders, but
# worded for a firm (Standort/Mitarbeitende) instead of a school (Klasse/Eltern).
# Served by the meta endpoint when the instance profile is "company" so the
# template editor starts from company text (M6 hard-separation).
COMPANY_STARTER_TEMPLATES: dict[str, dict[str, str]] = {
    "enrollment": {
        "subject": "Willkommen bei {{ school.name }}",
        "body_html": (
            "<h1>{{ subject }}</h1>\n"
            "<p>{{ salutation }}</p>\n"
            "<p>Wir freuen uns, {{ student.display_name }} bei "
            "<strong>{{ school.name }}</strong> begrüssen zu dürfen. "
            "Der erste Arbeitstag ist der {{ first_day }}.</p>\n"
            "<p>Die Zugangsdaten werden separat übergeben.</p>\n"
            "<p>Freundliche Grüsse<br>{{ signed_by }}<br>{{ school.name }}</p>\n"
        ),
    },
    "class_change": {
        "subject": "Interner Wechsel per {{ effective_date }}",
        "body_html": (
            "<h1>{{ subject }}</h1>\n"
            "<p>{{ salutation }}</p>\n"
            "<p>{{ student.display_name }} wechselt per {{ effective_date }} intern.</p>\n"
            "<p>Bei Fragen stehen wir gerne zur Verfügung.</p>\n"
            "<p>Freundliche Grüsse<br>{{ signed_by }}<br>{{ school.name }}</p>\n"
        ),
    },
    "password_handout": {
        "subject": "Neue Zugangsdaten für {{ student.display_name }}",
        "body_html": (
            "<h1>{{ subject }}</h1>\n"
            "<p>{{ salutation }}</p>\n"
            "<p>Das Passwort für {{ student.display_name }} "
            "({{ student.upn }}) wurde neu gesetzt:</p>\n"
            '<p style="font-size:1.4em"><strong>{{ temp_password }}</strong></p>\n'
            "<p>Bitte das Passwort beim ersten Anmelden ändern und sicher aufbewahren.</p>\n"
            "<p>Freundliche Grüsse<br>{{ signed_by }}<br>{{ school.name }}</p>\n"
        ),
    },
}


def starters_for_profile(profile: str) -> dict[str, dict[str, str]]:
    """Starter templates for the active instance profile (company vs school)."""
    return COMPANY_STARTER_TEMPLATES if profile == "company" else STARTER_TEMPLATES


class TemplateRenderError(ValueError):
    """A template body failed to render (bad Jinja / undefined variable)."""


class UnknownTemplateKeyError(ValueError):
    """The key is not an editable document-template key."""


@dataclass(frozen=True)
class ResolvedTemplate:
    """Welche Fassung für einen Brief gilt — das Ergebnis der Kette (ADR-0018 D3).

    `origin` und `locked` gehören ins Ergebnis und nicht in den Aufrufer: wer
    einen Brief erzeugt, soll im Audit oder in der Vorschau sagen können,
    *welche* Fassung gedruckt wurde. Ohne das Feld wäre „warum steht da ein
    anderer Text als in meinem Editor?" eine Frage, die nur die Datenbank
    beantwortet.
    """

    subject: str | None
    body_html: str
    #: "platform" oder "tenant".
    origin: str
    #: Die Plattformfassung, wenn eine gilt; sonst `None`.
    version: int | None = None
    #: Die Plattformfassung gilt, **weil** sie gesperrt ist — die eigene
    #: Fassung des Kunden liegt daneben und wurde übergangen.
    locked: bool = False


def _sandbox() -> SandboxedEnvironment:
    # autoescape=True (not select_autoescape): a from_string template is nameless
    # so select_autoescape would return False, leaving interpolated values (e.g.
    # a name containing "<") unescaped. The operator's literal HTML is untouched;
    # only substituted {{ … }} values are escaped.
    return SandboxedEnvironment(
        autoescape=True,
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
    )


def sample_context() -> dict[str, object]:
    """Representative values so the editor preview shows a realistic document."""
    return {
        "subject": "Beispiel-Betreff",
        "salutation": "Sehr geehrte Erziehungsberechtigte",
        "today": "24.08.2026",
        "signed_by": "Die Schulleitung",
        "recipient": ["Max Muster", "Schulweg 12", "3000 Musterhausen"],
        "school": {
            "name": "Schule Musterhausen",
            "locality": "Musterhausen",
            "address_line": "Schulhausstrasse 1",
            "contact": "sekretariat@schule.example.ch",
        },
        "student": {"display_name": "Max Muster", "upn": "max.muster@schule.example.ch"},
        "class_": {"name": "4a", "id": 1},
        "class_teacher": "Anna Meier",
        "school_year": "2026/27",
        "first_day": "18.08.2026",
        "old_class_name": "3a",
        "effective_date": "01.02.2027",
        "temp_password": "Tiger-Wolke-47",
    }


class DocumentTemplateService:
    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self.session = session
        self.repo = DocumentTemplateRepository(session)
        self.audit = AuditService(session, settings)

    @staticmethod
    def render_body(body_html: str, context: Mapping[str, object]) -> str:
        """Sandbox-render a template body. Raises TemplateRenderError on failure."""
        try:
            return _sandbox().from_string(body_html).render(**context)
        except TemplateError as exc:
            raise TemplateRenderError(str(exc)) from exc

    async def resolve(
        self, *, key: str, language: str, school_id: int | None
    ) -> DocumentTemplate | None:
        """Nur die eigene Fassung des Kunden — Standort vor global.

        Für die Bearbeitungsfläche. Wer einen Brief **druckt**, nimmt
        `resolve_effective`: dort entscheidet die vollständige Kette.
        """
        return await self.repo.resolve(key=key, language=language, school_id=school_id)

    async def resolve_effective(
        self, *, key: str, language: str, school_id: int | None
    ) -> ResolvedTemplate | None:
        """Die Kette aus ADR-0018 D3, an **einer** Stelle.

        1. Plattformfassung, wenn sie gesperrt ist (`may_override = False`)
        2. eigene Fassung für diesen Standort
        3. eigene globale Fassung
        4. Plattformfassung
        5. `None` — der Aufrufer nimmt die eingebaute Vorlage

        Absichtlich eine Funktion und nicht drei Bedingungen in drei
        Aufrufern: die Reihenfolge *ist* der Entscheid. Verstreut wäre sie
        beim nächsten Umbau an zwei von drei Stellen richtig.
        """
        platform = await self.repo.platform_row(key=key, language=language)
        if platform is not None and not platform.may_override:
            # Der Kunde hat vielleicht eine eigene Fassung. Sie bleibt liegen
            # (ADR-0018 D3) — gelöscht wird sie nicht, denn eine Sperre kann
            # zurückgenommen werden.
            return ResolvedTemplate(
                subject=platform.subject,
                body_html=platform.body_html,
                origin="platform",
                version=platform.version,
                locked=True,
            )
        own = await self.repo.resolve(key=key, language=language, school_id=school_id)
        if own is not None:
            return ResolvedTemplate(subject=own.subject, body_html=own.body_html, origin="tenant")
        if platform is not None:
            return ResolvedTemplate(
                subject=platform.subject,
                body_html=platform.body_html,
                origin="platform",
                version=platform.version,
            )
        return None

    async def list_for_admin(self, *, school_id: int | None) -> list[DocumentTemplate]:
        return await self.repo.list_for_admin(school_id=school_id)

    async def save(
        self,
        *,
        key: str,
        language: str,
        school_id: int | None,
        subject: str | None,
        body_html: str,
        is_active: bool,
        actor_upn: str | None,
        actor_object_guid: str | None,
        ip: str | None,
        request_id: str,
    ) -> DocumentTemplate:
        if key not in EDITABLE_KEYS:
            raise UnknownTemplateKeyError(key)
        # Fail fast on a broken template rather than storing something that
        # would 500 at document time.
        self.render_body(body_html, sample_context())
        row = await self.repo.upsert(
            key=key,
            language=language,
            school_id=school_id,
            subject=subject,
            body_html=body_html,
            is_active=is_active,
            updated_by=actor_upn,
        )
        await self.audit.emit(
            action="document_template_saved",
            target_kind="document_template",
            target_id=str(row.id),
            actor_upn=actor_upn,
            actor_object_guid=actor_object_guid,
            school_id=school_id,
            ip=ip,
            request_id=request_id,
            payload={"key": key, "language": language, "is_active": is_active},
        )
        return row

    async def delete(
        self,
        *,
        template_id: int,
        actor_upn: str | None,
        actor_object_guid: str | None,
        ip: str | None,
        request_id: str,
    ) -> bool:
        row = await self.repo.get(template_id)
        if row is None:
            return False
        key, language, school_id = row.key, row.language, row.school_id
        await self.repo.delete(row)
        await self.audit.emit(
            action="document_template_deleted",
            target_kind="document_template",
            target_id=str(template_id),
            actor_upn=actor_upn,
            actor_object_guid=actor_object_guid,
            school_id=school_id,
            ip=ip,
            request_id=request_id,
            payload={"key": key, "language": language},
        )
        return True


__all__ = [
    "EDITABLE_KEYS",
    "PLACEHOLDERS",
    "STARTER_TEMPLATES",
    "COMPANY_STARTER_TEMPLATES",
    "DocumentTemplateService",
    "ResolvedTemplate",
    "TemplateRenderError",
    "UnknownTemplateKeyError",
    "sample_context",
    "starters_for_profile",
]
