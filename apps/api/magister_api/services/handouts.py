"""Render credential hand-outs as PDFs (student + teacher provisioning, ADR 0006).

Two PDFs, zipped:
- a per-person slip (username + password), and
- an overview table (grouped by class for students, one group for teachers).

Passwords are received from the caller (the one-time apply response) and never
persisted. Rendered in the three Swiss national languages (de/fr/it).
"""

from __future__ import annotations

import io
import zipfile
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape
from weasyprint import HTML

_TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "letters" / "templates"

AUDIENCE_STUDENTS = "students"
AUDIENCE_TEACHERS = "teachers"

# Internal PDF filenames inside the ZIP, per audience.
_FILES: dict[str, tuple[str, str]] = {
    AUDIENCE_STUDENTS: ("schueler-handouts.pdf", "klassen-uebersicht.pdf"),
    AUDIENCE_TEACHERS: ("lehrpersonen-handouts.pdf", "lehrpersonen-uebersicht.pdf"),
}

# Backwards-compatible aliases (student defaults) for existing imports/tests.
HANDOUT_FILE = _FILES[AUDIENCE_STUDENTS][0]
CLASS_TABLE_FILE = _FILES[AUDIENCE_STUDENTS][1]

# Hand-out strings in the three Swiss national languages. Unknown languages
# (e.g. "en") fall back to German.
_STRINGS: dict[str, dict[str, str]] = {
    "de": {
        "title": "Deine Zugangsdaten",
        "teacher_title": "Ihre Zugangsdaten",
        "class_label": "Klasse",
        "teachers_group": "Lehrpersonen",
        # Student username = MS365; teacher username = Online/Nextcloud (overlaid
        # below). "username_pc" is the sAMAccountName for the PC login.
        "username": "Benutzername MS365",
        "teacher_username": "Benutzername Online / Nextcloud",
        "username_pc": "Benutzername PC",
        # Teacher-only mandatory note below the password (empty for students).
        "pw_change_note": "",
        "teacher_pw_change_note": (
            "Passwort beim ersten Einloggen unbedingt ändern. Das neue Passwort "
            "niemandem weitergeben und nirgends aufschreiben."
        ),
        "password": "Passwort",
        "force_change_note": "Beim ersten Anmelden musst du ein neues Passwort setzen.",
        "teacher_force_change_note": ("Beim ersten Anmelden müssen Sie ein neues Passwort setzen."),
        "keep_safe": "Bewahre diesen Zettel sicher auf und gib ihn niemandem weiter.",
        "teacher_keep_safe": (
            "Bewahren Sie diesen Zettel sicher auf und geben Sie ihn niemandem weiter."
        ),
        "students": "Schüler:innen",
        "name": "Name",
        "change": "Wechsel",
        "yes": "ja",
        "no": "nein",
        "confidential": "Vertraulich — nur für die Lehrperson. Nach der Übergabe vernichten.",
        "teacher_confidential": "Vertraulich — nach der Übergabe vernichten.",
    },
    "fr": {
        "title": "Tes identifiants",
        "teacher_title": "Vos identifiants",
        "class_label": "Classe",
        "teachers_group": "Enseignant·es",
        "username": "Nom d'utilisateur MS365",
        "teacher_username": "Nom d'utilisateur en ligne / Nextcloud",
        "username_pc": "Nom d'utilisateur PC",
        "pw_change_note": "",
        "teacher_pw_change_note": (
            "Changez impérativement le mot de passe lors de la première connexion. "
            "Ne communiquez le nouveau mot de passe à personne et ne l'écrivez nulle part."
        ),
        "password": "Mot de passe",
        "force_change_note": (
            "Lors de la première connexion, tu devras définir un nouveau mot de passe."
        ),
        "teacher_force_change_note": (
            "Lors de la première connexion, vous devrez définir un nouveau mot de passe."
        ),
        "keep_safe": "Conserve cette feuille en lieu sûr et ne la donne à personne.",
        "teacher_keep_safe": ("Conservez cette feuille en lieu sûr et ne la donnez à personne."),
        "students": "élèves",
        "name": "Nom",
        "change": "Changement",
        "yes": "oui",
        "no": "non",
        "confidential": "Confidentiel — réservé à l'enseignant. À détruire après la remise.",
        "teacher_confidential": "Confidentiel — à détruire après la remise.",
    },
    "it": {
        "title": "Le tue credenziali",
        "teacher_title": "Le sue credenziali",
        "class_label": "Classe",
        "teachers_group": "Docenti",
        "username": "Nome utente MS365",
        "teacher_username": "Nome utente online / Nextcloud",
        "username_pc": "Nome utente PC",
        "pw_change_note": "",
        "teacher_pw_change_note": (
            "Cambiare assolutamente la password al primo accesso. Non comunicare "
            "la nuova password a nessuno e non annotarla da nessuna parte."
        ),
        "password": "Password",
        "force_change_note": "Al primo accesso dovrai impostare una nuova password.",
        "teacher_force_change_note": "Al primo accesso dovrà impostare una nuova password.",
        "keep_safe": "Conserva questo foglio in un luogo sicuro e non darlo a nessuno.",
        "teacher_keep_safe": ("Conservi questo foglio in un luogo sicuro e non lo dia a nessuno."),
        "students": "studenti",
        "name": "Nome",
        "change": "Cambio",
        "yes": "sì",
        "no": "no",
        "confidential": "Riservato — solo per il docente. Distruggere dopo la consegna.",
        "teacher_confidential": "Riservato — distruggere dopo la consegna.",
    },
}


def _strings_for(language: str) -> dict[str, str]:
    return _STRINGS.get((language or "de").lower()[:2], _STRINGS["de"])


@dataclass(frozen=True)
class HandoutEntry:
    upn: str
    sam_account_name: str
    display_name: str
    class_name: str
    password: str
    force_change: bool


@dataclass(frozen=True)
class _ClassGroup:
    class_name: str
    entries: list[HandoutEntry]
    group_heading: str


def _build_env() -> Environment:
    return Environment(
        loader=FileSystemLoader(str(_TEMPLATES_DIR)),
        autoescape=select_autoescape(["html", "xml"]),
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
    )


def _group_by_class(
    entries: list[HandoutEntry], *, strings: dict[str, str], teachers: bool
) -> list[_ClassGroup]:
    if teachers:
        # Teachers have no class — one flat group titled "Lehrpersonen".
        ordered = sorted(entries, key=lambda x: x.display_name.lower())
        heading = f"{strings['teachers_group']} — {len(ordered)}"
        return [_ClassGroup(class_name="", entries=ordered, group_heading=heading)]
    grouped: OrderedDict[str, list[HandoutEntry]] = OrderedDict()
    for e in sorted(entries, key=lambda x: (x.class_name, x.display_name.lower())):
        grouped.setdefault(e.class_name, []).append(e)
    return [
        _ClassGroup(
            class_name=k,
            entries=v,
            group_heading=f"{strings['class_label']} {k} — {len(v)} {strings['students']}",
        )
        for k, v in grouped.items()
    ]


def _html_to_pdf(html: str) -> bytes:
    pdf = HTML(string=html, base_url=str(_TEMPLATES_DIR)).write_pdf()
    if pdf is None:  # pragma: no cover - WeasyPrint always returns bytes
        raise RuntimeError("WeasyPrint returned no PDF bytes")
    return pdf


def render_handouts_zip(
    entries: list[HandoutEntry],
    *,
    school_name: str,
    generated_on: str,
    language: str = "de",
    audience: str = AUDIENCE_STUDENTS,
) -> bytes:
    """Render both hand-out PDFs and return them as a single ZIP archive.

    ``language`` is one of de/fr/it (Swiss national languages); anything else
    falls back to German. ``audience`` selects student vs teacher wording
    (title, group heading, confidentiality note) and the internal filenames.
    Pure/synchronous (WeasyPrint) — call via ``run_in_threadpool``.
    """
    teachers = audience == AUDIENCE_TEACHERS
    env = _build_env()
    base = _strings_for(language)
    # Overlay the audience-specific wording onto the base strings so the
    # templates stay audience-agnostic (they read the same keys).
    strings = dict(base)
    if teachers:
        strings["title"] = base["teacher_title"]
        strings["username"] = base["teacher_username"]
        strings["force_change_note"] = base["teacher_force_change_note"]
        strings["keep_safe"] = base["teacher_keep_safe"]
        strings["confidential"] = base["teacher_confidential"]
        strings["pw_change_note"] = base["teacher_pw_change_note"]

    sorted_entries = sorted(entries, key=lambda x: (x.class_name, x.display_name.lower()))
    handouts_html = env.get_template("student_handouts.html").render(
        entries=sorted_entries, school_name=school_name, generated_on=generated_on, t=strings
    )
    table_html = env.get_template("student_class_table.html").render(
        groups=_group_by_class(entries, strings=strings, teachers=teachers),
        school_name=school_name,
        generated_on=generated_on,
        t=strings,
    )
    handouts_pdf = _html_to_pdf(handouts_html)
    table_pdf = _html_to_pdf(table_html)

    slip_file, table_file = _FILES.get(audience, _FILES[AUDIENCE_STUDENTS])
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(slip_file, handouts_pdf)
        zf.writestr(table_file, table_pdf)
    return buf.getvalue()


__all__ = [
    "AUDIENCE_STUDENTS",
    "AUDIENCE_TEACHERS",
    "CLASS_TABLE_FILE",
    "HANDOUT_FILE",
    "HandoutEntry",
    "render_handouts_zip",
]
