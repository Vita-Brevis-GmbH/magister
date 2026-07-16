"""Hand-out rendering: teacher audience + MS365/PC usernames + password note."""

from __future__ import annotations

import io
import zipfile

from magister_api.services.handouts import (
    AUDIENCE_TEACHERS,
    HandoutEntry,
    _build_env,
    _group_by_class,
    _strings_for,
    render_handouts_zip,
)


def _entries() -> list[HandoutEntry]:
    return [
        HandoutEntry(
            upn="erika.lehrer@schule.ch",
            sam_account_name="erika.lehrer",
            display_name="Erika Lehrer",
            class_name="",  # teachers have no class
            password="Ab3!ef2hkmnp",
            force_change=True,
        ),
        HandoutEntry(
            upn="max.kollege@schule.ch",
            sam_account_name="max.kollege",
            display_name="Max Kollege",
            class_name="",
            password="Zx9-qw4rtypq",
            force_change=False,
        ),
    ]


def _render_slip(*, teachers: bool) -> str:
    """Render the slip template exactly as render_handouts_zip does."""
    base = _strings_for("de")
    strings = dict(base)
    if teachers:
        strings["title"] = base["teacher_title"]
        strings["username"] = base["teacher_username"]
        strings["force_change_note"] = base["teacher_force_change_note"]
        strings["keep_safe"] = base["teacher_keep_safe"]
        strings["pw_change_note"] = base["teacher_pw_change_note"]
    return (
        _build_env()
        .get_template("student_handouts.html")
        .render(entries=_entries(), school_name="Schule A", generated_on="16.07.2026", t=strings)
    )


def test_teacher_group_heading_has_no_class_label() -> None:
    groups = _group_by_class(_entries(), strings=_strings_for("de"), teachers=True)
    assert len(groups) == 1
    assert groups[0].group_heading == "Lehrpersonen — 2"
    assert "Klasse" not in groups[0].group_heading


def test_teacher_zip_uses_teacher_filenames() -> None:
    data = render_handouts_zip(
        _entries(),
        school_name="Schule A",
        generated_on="16.07.2026",
        language="de",
        audience=AUDIENCE_TEACHERS,
    )
    names = set(zipfile.ZipFile(io.BytesIO(data)).namelist())
    assert names == {"lehrpersonen-handouts.pdf", "lehrpersonen-uebersicht.pdf"}


def test_teacher_slip_labels_and_note() -> None:
    html = _render_slip(teachers=True)
    assert "Benutzername Online / Nextcloud" in html
    assert "Benutzername PC" in html
    assert "erika.lehrer@schule.ch" in html  # online username = UPN
    assert "erika.lehrer" in html  # PC username = sAMAccountName
    assert "Passwort beim ersten Einloggen unbedingt ändern" in html


def test_student_slip_labels_and_no_teacher_note() -> None:
    html = _render_slip(teachers=False)
    assert "Benutzername MS365" in html
    assert "Benutzername PC" in html
    assert "Passwort beim ersten Einloggen unbedingt ändern" not in html


def test_student_zip_unchanged_filenames() -> None:
    data = render_handouts_zip(
        [
            HandoutEntry(
                upn="anna@schule.ch",
                sam_account_name="anna.muster",
                display_name="Anna Muster",
                class_name="3a",
                password="Tiger-Wolke-47",
                force_change=True,
            )
        ],
        school_name="Schule A",
        generated_on="16.07.2026",
    )
    names = set(zipfile.ZipFile(io.BytesIO(data)).namelist())
    assert names == {"schueler-handouts.pdf", "klassen-uebersicht.pdf"}
