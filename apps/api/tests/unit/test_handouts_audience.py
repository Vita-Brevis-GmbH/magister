"""Hand-out rendering: teacher audience uses teacher wording + filenames."""

from __future__ import annotations

import io
import zipfile

from magister_api.services.handouts import (
    AUDIENCE_TEACHERS,
    HandoutEntry,
    _group_by_class,
    _strings_for,
    render_handouts_zip,
)


def _entries() -> list[HandoutEntry]:
    return [
        HandoutEntry(
            upn="erika.lehrer@schule.ch",
            display_name="Erika Lehrer",
            class_name="",  # teachers have no class
            password="Ab3!ef2hkmnp",
            force_change=True,
        ),
        HandoutEntry(
            upn="max.kollege@schule.ch",
            display_name="Max Kollege",
            class_name="",
            password="Zx9#qw4rtypq",
            force_change=False,
        ),
    ]


def test_teacher_group_heading_has_no_class_label() -> None:
    groups = _group_by_class(_entries(), strings=_strings_for("de"), teachers=True)
    assert len(groups) == 1
    heading = groups[0].group_heading
    assert "Lehrpersonen" in heading
    assert heading == "Lehrpersonen — 2"
    assert "Klasse" not in heading
    assert "Schüler" not in heading


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


def test_student_zip_unchanged() -> None:
    data = render_handouts_zip(
        [
            HandoutEntry(
                upn="anna@schule.ch",
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
