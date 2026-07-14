"""Render a class password list PDF (names + usernames + stored passwords).

Only makes sense with the password vault on: for each active student of the
class the stored password is shown when present, otherwise a placeholder. The
plaintext is decrypted on the fly via :class:`PasswordVaultService` and never
leaves this request. Confidential — for the teacher only.
"""

from __future__ import annotations

from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool
from weasyprint import HTML

from magister_api.config import Settings
from magister_api.models.school import School
from magister_api.models.school_class import SchoolClass
from magister_api.repositories.base import ScopeContext
from magister_api.services._user_enrich import fetch_user_labels
from magister_api.services.class_memberships import ClassMembershipService, ClassNotInScopeError
from magister_api.services.password_vault import PasswordVaultService

_TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "letters" / "templates"

_STRINGS: dict[str, dict[str, str]] = {
    "de": {
        "title": "Passwortliste",
        "class_label": "Klasse",
        "name": "Name",
        "username": "Benutzername",
        "password": "Passwort",
        "not_stored": "— nicht gespeichert —",
        "empty": "Keine Schüler:innen in dieser Klasse.",
        "confidential": "Vertraulich — nur für die Lehrperson. Sicher aufbewahren.",
    },
    "fr": {
        "title": "Liste des mots de passe",
        "class_label": "Classe",
        "name": "Nom",
        "username": "Nom d'utilisateur",
        "password": "Mot de passe",
        "not_stored": "— non enregistré —",
        "empty": "Aucun élève dans cette classe.",
        "confidential": "Confidentiel — réservé à l'enseignant. À conserver en lieu sûr.",
    },
    "it": {
        "title": "Elenco password",
        "class_label": "Classe",
        "name": "Nome",
        "username": "Nome utente",
        "password": "Password",
        "not_stored": "— non salvata —",
        "empty": "Nessun allievo in questa classe.",
        "confidential": "Riservato — solo per il docente. Conservare in luogo sicuro.",
    },
}


def _strings_for(language: str) -> dict[str, str]:
    return _STRINGS.get((language or "de").lower()[:2], _STRINGS["de"])


class ClassNotFoundError(LookupError):
    pass


class ClassPasswordListService:
    def __init__(self, session: AsyncSession, settings: Settings, scope: ScopeContext) -> None:
        self.session = session
        self.settings = settings
        self.scope = scope

    async def render(self, *, class_id: int, language: str, generated_on: str) -> tuple[bytes, str]:
        svc = ClassMembershipService(self.session, self.settings, self.scope)
        try:
            memberships = await svc.list_active(class_id, include_upcoming=True)
        except ClassNotInScopeError as exc:
            raise ClassNotFoundError(str(class_id)) from exc

        cls = await self.session.get(SchoolClass, class_id)
        if cls is None:
            raise ClassNotFoundError(str(class_id))
        school_name = ""
        school = await self.session.get(School, cls.school_id)
        if school is not None:
            school_name = school.name

        labels = await fetch_user_labels(self.session, (m.ad_object_guid for m in memberships))
        vault = PasswordVaultService(self.session, self.settings)
        vault_on = await vault.enabled()

        rows: list[dict[str, str | None]] = []
        for m in memberships:
            lbl = labels.get(m.ad_object_guid)
            pw = await vault.get(m.ad_object_guid) if vault_on else None
            rows.append(
                {
                    "name": (lbl.display_name if lbl else None) or m.ad_object_guid,
                    "upn": (lbl.upn if lbl else None) or "",
                    "password": pw,
                }
            )
        rows.sort(key=lambda r: str(r["name"]).lower())

        class_name = cls.name + (f" ({cls.kuerzel})" if cls.kuerzel else "")
        html = self._render_html(
            rows=rows,
            class_name=class_name,
            school_name=school_name,
            generated_on=generated_on,
            language=language,
        )
        pdf = await run_in_threadpool(_sync_html_to_pdf, html)
        filename = f"passwortliste-{cls.kuerzel or cls.name}.pdf"
        return pdf, filename

    def _render_html(
        self,
        *,
        rows: list[dict[str, str | None]],
        class_name: str,
        school_name: str,
        generated_on: str,
        language: str,
    ) -> str:
        env = Environment(
            loader=FileSystemLoader(str(_TEMPLATES_DIR)),
            autoescape=select_autoescape(["html", "xml"]),
            undefined=StrictUndefined,
            trim_blocks=True,
            lstrip_blocks=True,
        )
        return env.get_template("class_password_list.html").render(
            t=_strings_for(language),
            rows=rows,
            class_name=class_name,
            school_name=school_name,
            generated_on=generated_on,
        )


def _sync_html_to_pdf(html: str) -> bytes:
    pdf = HTML(string=html, base_url=str(_TEMPLATES_DIR)).write_pdf()
    if pdf is None:  # pragma: no cover - WeasyPrint always returns bytes
        raise RuntimeError("WeasyPrint returned no PDF bytes")
    return pdf


__all__ = ["ClassNotFoundError", "ClassPasswordListService"]
