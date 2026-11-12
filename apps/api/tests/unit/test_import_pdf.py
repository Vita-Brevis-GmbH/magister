"""PDF-Klassenliste → Passwort-Zeilen.

Das Test-PDF wird im Layout der Klassenlisten alter Anlagen erzeugt: schmale
Spalten, sodass Passwörter und UPNs am Bindestrich umbrechen.
"""

from __future__ import annotations

import pytest
from weasyprint import HTML

from magister_api.services.import_pdf import (
    PdfImportError,
    looks_like_pdf,
    password_rows_from_pdf,
)

_CSS = """
@page { size: A4; margin: 15mm; }
body { font: 11pt sans-serif; }
table { border-collapse: collapse; width: 100%; }
th, td { border: 1px solid #333; padding: 4px; }
th.narrow, td.narrow { width: 22mm; }
"""


def klassenliste(
    rows: list[tuple[str, str, str, str, str]],
    *,
    header: tuple[str, ...] = (
        "Name",
        "Benutzername MS365",
        "Benutzername PC",
        "Passwort",
        "Wechsel",
    ),
    title: str = "Klasse 4 — Testliste",
) -> bytes:
    head = "".join(f'<th class="narrow">{h}</th>' for h in header)
    body = "".join(
        "<tr>" + "".join(f'<td class="narrow">{c}</td>' for c in r) + "</tr>" for r in rows
    )
    html = (
        f"<html><head><style>{_CSS}</style></head><body><h1>{title}</h1>"
        f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"
        "<p>Vertraulich — nur für die Lehrperson.</p></body></html>"
    )
    pdf = HTML(string=html).write_pdf()
    assert pdf is not None
    return pdf


ROWS = [
    ("Alessia Josephine Schleicher", "al.schleicher@sus-seftigen.ch", "al.schleicher",
     "Loewe-Sofa-82", "nein"),
    ("Ben Muster", "ben.muster@sus-seftigen.ch", "be.muster", "Tiger-Berg-17", "ja"),
]  # fmt: skip


def test_reads_cells_and_keeps_the_hyphen_at_a_wrap() -> None:
    data = klassenliste(ROWS)
    assert looks_like_pdf(data)
    rows = password_rows_from_pdf(data)
    assert rows == [
        {
            "name": "Alessia Josephine Schleicher",
            "upn": "al.schleicher@sus-seftigen.ch",
            "sam_account_name": "al.schleicher",
            "password": "Loewe-Sofa-82",
            "force_change": "nein",
        },
        {
            "name": "Ben Muster",
            "upn": "ben.muster@sus-seftigen.ch",
            "sam_account_name": "be.muster",
            "password": "Tiger-Berg-17",
            "force_change": "ja",
        },
    ]


def test_long_list_over_several_pages_skips_repeated_headers() -> None:
    many = [
        (f"Kind {i}", f"kind{i}@schule.ch", f"kind{i}", f"Wald-Weg-{i:02d}", "nein")
        for i in range(70)
    ]
    rows = password_rows_from_pdf(klassenliste(many))
    assert [r["sam_account_name"] for r in rows] == [f"kind{i}" for i in range(70)]
    assert all(r["password"] == f"Wald-Weg-{i:02d}" for i, r in enumerate(rows))


def test_columns_are_found_by_header_not_position() -> None:
    data = klassenliste(
        [("Tiger-Berg-17", "be.muster", "Ben Muster")],  # type: ignore[list-item]
        header=("Kennwort", "Benutzername", "Name"),
    )
    rows = password_rows_from_pdf(data)
    # "Benutzername" ohne @ in den Werten ist der PC-Anmeldename.
    assert rows == [
        {
            "name": "Ben Muster",
            "upn": "",
            "sam_account_name": "be.muster",
            "password": "Tiger-Berg-17",
            "force_change": "",
        }
    ]


def test_a_pdf_without_password_table_is_refused() -> None:
    data = klassenliste([("Ben", "Muster", "x", "y", "z")], header=("A", "B", "C", "D", "E"))
    with pytest.raises(PdfImportError, match="pdf_no_password_table"):
        password_rows_from_pdf(data)


def test_garbage_is_unreadable() -> None:
    with pytest.raises(PdfImportError, match="pdf_unreadable"):
        password_rows_from_pdf(b"%PDF-1.7\nkaputt")
    assert not looks_like_pdf(b"upn,password\n")
