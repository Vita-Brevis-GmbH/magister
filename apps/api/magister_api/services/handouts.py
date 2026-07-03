"""Render student credential hand-outs as PDFs (student provisioning, ADR 0006).

Two PDFs, zipped:
- ``schueler-handouts.pdf`` — one slip per student (username + password).
- ``klassen-uebersicht.pdf`` — one table per class listing all students.

Passwords are received from the caller (the one-time apply response) and never
persisted. German-only for now, mirroring the parent-letter templates.
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

HANDOUT_FILE = "schueler-handouts.pdf"
CLASS_TABLE_FILE = "klassen-uebersicht.pdf"

# German strings for the hand-out PDFs (parent-facing letters are German-only
# too; see docs/runbooks/upgrade-to-m3 known limitations).
_STRINGS_DE = {
    "title": "Deine Zugangsdaten",
    "class_label": "Klasse",
    "username": "Benutzername",
    "password": "Passwort",
    "force_change_note": "Beim ersten Anmelden musst du ein neues Passwort setzen.",
    "keep_safe": "Bewahre diesen Zettel sicher auf und gib ihn niemandem weiter.",
    "students": "Schüler:innen",
    "name": "Name",
    "change": "Wechsel",
    "yes": "ja",
    "no": "nein",
    "confidential": "Vertraulich — nur für die Lehrperson. Nach der Übergabe vernichten.",
}


@dataclass(frozen=True)
class HandoutEntry:
    upn: str
    display_name: str
    class_name: str
    password: str
    force_change: bool


@dataclass(frozen=True)
class _ClassGroup:
    class_name: str
    entries: list[HandoutEntry]


def _build_env() -> Environment:
    return Environment(
        loader=FileSystemLoader(str(_TEMPLATES_DIR)),
        autoescape=select_autoescape(["html", "xml"]),
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
    )


def _group_by_class(entries: list[HandoutEntry]) -> list[_ClassGroup]:
    grouped: OrderedDict[str, list[HandoutEntry]] = OrderedDict()
    for e in sorted(entries, key=lambda x: (x.class_name, x.display_name.lower())):
        grouped.setdefault(e.class_name, []).append(e)
    return [_ClassGroup(class_name=k, entries=v) for k, v in grouped.items()]


def _html_to_pdf(html: str) -> bytes:
    pdf = HTML(string=html, base_url=str(_TEMPLATES_DIR)).write_pdf()
    if pdf is None:  # pragma: no cover - WeasyPrint always returns bytes
        raise RuntimeError("WeasyPrint returned no PDF bytes")
    return pdf


def render_handouts_zip(
    entries: list[HandoutEntry], *, school_name: str, generated_on: str
) -> bytes:
    """Render both hand-out PDFs and return them as a single ZIP archive.

    Pure/synchronous (WeasyPrint) — call via ``run_in_threadpool``.
    """
    env = _build_env()
    sorted_entries = sorted(entries, key=lambda x: (x.class_name, x.display_name.lower()))
    handouts_html = env.get_template("student_handouts.html").render(
        entries=sorted_entries, school_name=school_name, generated_on=generated_on, t=_STRINGS_DE
    )
    table_html = env.get_template("student_class_table.html").render(
        groups=_group_by_class(entries),
        school_name=school_name,
        generated_on=generated_on,
        t=_STRINGS_DE,
    )
    handouts_pdf = _html_to_pdf(handouts_html)
    table_pdf = _html_to_pdf(table_html)

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(HANDOUT_FILE, handouts_pdf)
        zf.writestr(CLASS_TABLE_FILE, table_pdf)
    return buf.getvalue()


__all__ = ["CLASS_TABLE_FILE", "HANDOUT_FILE", "HandoutEntry", "render_handouts_zip"]
