"""Passwort-Import aus einer PDF-Klassenliste — die Ausnahme neben der CSV.

Alte Anlagen geben Klassenlisten oft nur als PDF heraus: eine Tabelle mit
Name, Benutzername (UPN und/oder PC-Anmeldename), Passwort und einer Spalte
"Wechsel" (ja/nein). Die Spalten werden an der Kopfzeile erkannt, nicht an
ihrer Position.

Gelesen wird zellenweise: bricht eine Zelle um ("Loewe-" / "Sofa-82"), werden
die Zeilen ohne Trennzeichen zusammengefügt — der Bindestrich steht schon in
der Zelle. Nur Namen werden mit Leerzeichen verbunden. Fliesstext-Extraktion
verlöre genau diesen Bindestrich.

Der Inhalt (Passwörter!) wird nie geloggt; pdfminer selbst wird stumm gestellt.
"""

from __future__ import annotations

import io
import logging
import re

import pdfplumber

# pdfminer loggt auf DEBUG Inhalte aus dem Dokument — nie in unsere Logs.
logging.getLogger("pdfminer").setLevel(logging.ERROR)

#: Eine Klassenliste hat eine Handvoll Seiten; mehr ist kein Klassen-PDF.
MAX_PAGES = 50
MAX_ROWS = 2000


class PdfImportError(ValueError):
    """Das PDF ist kein lesbares Klassen-PDF. ``str(exc)`` ist der Fehlercode."""


def _norm(text: str) -> str:
    return " ".join(text.split()).casefold()


def _column_role(header: str) -> str | None:
    """Welche Spalte eine Kopfzelle bezeichnet (de · fr · it · en)."""
    h = _norm(header)
    words = set(re.findall(r"\w+", h))
    if not words:
        return None
    if words & {"passwort", "kennwort", "password", "passe", "pw"}:
        return "password"
    if words & {"wechsel", "ändern", "aendern", "änderung", "force_change", "changer", "cambio"}:
        return "force_change"
    if words & {"ms365", "m365", "o365", "office", "upn", "mail", "email"} or "e-mail" in h:
        return "upn"
    if words & {"pc", "sam", "windows", "anmeldename", "login", "sam_account_name"}:
        return "sam_account_name"
    if words & {"benutzername", "benutzer", "utilisateur", "utente", "username", "user"}:
        # "Benutzername" allein: was drin steht, entscheidet (siehe _fix_roles).
        return "username"
    if words & {"name", "nom", "nome", "schüler", "schülerin", "vorname", "nachname"}:
        return "name"
    return None


def _header_map(row: list[str | None]) -> dict[int, str] | None:
    """Spalten-Rollen einer Kopfzeile, oder ``None``, wenn es keine ist."""
    roles = {i: r for i, cell in enumerate(row) if (r := _column_role(cell or ""))}
    found = set(roles.values())
    if "password" not in found or not {"upn", "sam_account_name", "username"} & found:
        return None
    return roles


def _cell(value: str | None, role: str) -> str:
    lines = [ln.strip() for ln in (value or "").splitlines() if ln.strip()]
    return (" " if role == "name" else "").join(lines)


def _fix_roles(roles: dict[int, str], body: list[list[str | None]]) -> dict[int, str]:
    """Eine Spalte "Benutzername" ist UPN, wenn ihre Werte ein @ tragen."""
    fixed = dict(roles)
    for i, role in roles.items():
        if role != "username":
            continue
        filled = [v for r in body if (v := _cell(r[i] if i < len(r) else None, role))]
        guess = "upn" if filled and all("@" in v for v in filled) else "sam_account_name"
        del fixed[i]
        if guess not in fixed.values():
            fixed[i] = guess
    return fixed


def _tables(data: bytes) -> list[list[list[str | None]]]:
    try:
        with pdfplumber.open(io.BytesIO(data)) as pdf:
            if len(pdf.pages) > MAX_PAGES:
                raise PdfImportError("pdf_too_many_pages")
            out: list[list[list[str | None]]] = []
            for page in pdf.pages:
                out.extend(page.extract_tables())
            return out
    except PdfImportError:
        raise
    except Exception as exc:  # noqa: BLE001 — jedes kaputte PDF ist "unlesbar"
        raise PdfImportError("pdf_unreadable") from exc


_WS = re.compile(r"\s+")


def password_rows_from_pdf(data: bytes) -> list[dict[str, str]]:
    """Zeilen ``{name, upn, sam_account_name, password, force_change}`` aus dem PDF.

    Fehlende Spalten bleiben leer. Tabellen ohne eigene Kopfzeile (Folgeseiten)
    übernehmen die Spalten der vorherigen Tabelle, wenn die Breite passt.
    """
    rows: list[dict[str, str]] = []
    current: dict[int, str] | None = None
    header_cells: list[str] = []
    for table in _tables(data):
        if not table:
            continue
        header = _header_map(table[0])
        if header is not None:
            body = table[1:]
            current = _fix_roles(header, body)
            header_cells = [_norm(c or "") for c in table[0]]
        elif current is not None and len(table[0]) == len(header_cells):
            body = table
        else:
            continue
        for raw in body:
            # Wiederholte Kopfzeile (Seitenumbruch) überspringen.
            if [_norm(c or "") for c in raw] == header_cells:
                continue
            row = {
                role: _cell(raw[i] if i < len(raw) else None, role) for i, role in current.items()
            }
            if not any(row.values()):
                continue
            row["upn"] = _WS.sub("", row.get("upn", "")).lower()
            row["sam_account_name"] = _WS.sub("", row.get("sam_account_name", ""))
            rows.append(
                {
                    k: row.get(k, "")
                    for k in ("name", "upn", "sam_account_name", "password", "force_change")
                }
            )
            if len(rows) > MAX_ROWS:
                raise PdfImportError("pdf_too_many_rows")
    if current is None:
        raise PdfImportError("pdf_no_password_table")
    return rows


def looks_like_pdf(data: bytes) -> bool:
    return data[:5] == b"%PDF-"
