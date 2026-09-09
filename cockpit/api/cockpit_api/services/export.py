"""Kundenexport: CSV je Tabelle, JSON-Manifest, Prüfsumme (ADR-0016 D7).

Das Abnahmekriterium ist „ein Export ist ohne Magister lesbar“, und das ist
strenger als es klingt. Eine CSV allein genügt nicht: wer sie in zwei Jahren
öffnet, muss wissen, wie die Felder heissen, was ``valid_to`` leer bedeutet,
welches Trennzeichen gilt und was **nicht** drin ist. Deshalb liegt neben den
Daten ein Manifest, das jede Datei und jede Spalte beschreibt, und eine
README, die dasselbe in Prosa sagt.

Drei Festlegungen, die in der Praxis den Unterschied machen:

* **Trennzeichen ``;``, Kodierung ``utf-8-sig``.** Nicht Komma und nicht
  reines UTF-8: der Empfänger ist eine Gemeinde-IT mit Excel in einer
  deutschsprachigen Windows-Installation, und dort öffnet genau diese
  Kombination per Doppelklick richtig — mit Komma landet alles in einer
  Spalte, ohne BOM werden die Umlaute falsch. Beides steht ausdrücklich im
  Manifest, damit auch ein Programm es nicht raten muss.
* **Werte in einer Form, die kein Magister-Wissen braucht.** Zeitstempel als
  ISO 8601 mit Zeitzone, Wahrheitswerte als ``true``/``false``, Listen und
  JSONB als JSON, NULL als leeres Feld. Ohne diese Festlegung ist ein Feld mit
  ``{}`` nicht von einem Feld mit dem Text ``{}`` zu unterscheiden.
* **Sortiert.** Zwei Exporte desselben Stands ergeben dieselben Dateien. Ein
  Kunde, der vor und nach einer Änderung exportiert, kann sie vergleichen.

Was hier **nicht** passiert: verschlüsseln. Ein Export ist dazu da, gelesen zu
werden. Der Preis dafür ist, dass er der einzige Ort ist, an dem Kundendaten
im Klartext liegen — deshalb ein eigenes Verzeichnis mit ``0700``, eine Frist
(``COCKPIT_EXPORT_TTL_DAYS``) und ein Audit-Ereignis bei jedem Download.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import logging
import os
import re
import zipfile
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine

from cockpit_api.services.backup import IDENTIFIER_PATTERN
from cockpit_api.services.export_plan import (
    COLUMN_NOTES,
    EXPORT_TABLES,
    NOT_EXPORTED,
    ExportTable,
    forbidden_column,
)

logger = logging.getLogger(__name__)

#: Fassung des Exportformats. Ändert sich, wenn sich die Bedeutung eines
#: Feldes ändert — ein Kunde mit einem alten Export soll das sehen können.
FORMAT_VERSION = 1

#: Trennzeichen und Kodierung. Begründung im Modul-Docstring.
CSV_DELIMITER = ";"
CSV_ENCODING = "utf-8-sig"

#: Dateiname-Zeichen, die wir in einer Vorlagendatei zulassen.
SAFE_FILENAME = re.compile(r"[^a-zA-Z0-9._-]+")


class ExportError(RuntimeError):
    """Der Export ist gescheitert. Es bleibt keine halbe Datei liegen."""


@dataclass(frozen=True, slots=True)
class ExportArtifact:
    path: Path
    size_bytes: int
    checksum_sha256: str
    row_counts: dict[str, int]


def _qualified(schema: str, table: str) -> str:
    for value, field in ((schema, "schema_name"), (table, "table")):
        if not IDENTIFIER_PATTERN.match(value):
            raise ExportError(f"{field}={value!r} ist kein zulässiger Bezeichner.")
    return f'"{schema}"."{table}"'


def _cell(value: object) -> str:
    """Einen Wert so schreiben, dass er ohne Magister eindeutig ist."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, datetime):
        # Mit Zeitzone. Ein Zeitstempel ohne Offset ist in einem Export, den
        # jemand in einer anderen Zeitzone liest, eine Falle.
        return value.isoformat()
    if isinstance(value, list | dict):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    if isinstance(value, bytes | memoryview):
        # Sollte nach export_plan nicht vorkommen; wenn doch, dann sichtbar
        # als Hinweis und nicht als kaputtes Zeichen im CSV.
        raise ExportError(
            "Eine Binärspalte ist im Export gelandet. Das ist ein Fehler in "
            "export_plan.EXPORT_TABLES, nicht in den Daten."
        )
    return str(value)


def _check_plan() -> None:
    """Die Allowlist gegen die Spaltenregel prüfen — bei jedem Export.

    Nicht nur im Test: ein Export ist der eine Ort, an dem Kundendaten im
    Klartext liegen, und der Fehler wäre irreversibel, sobald die Datei den
    Kunden erreicht hat.
    """
    for entry in EXPORT_TABLES:
        if not IDENTIFIER_PATTERN.match(entry.table):
            raise ExportError(f"{entry.table!r} ist kein zulässiger Tabellenname.")
        if not entry.columns:
            raise ExportError(f"{entry.table} ist ohne Spalten eingetragen.")
        for column in entry.columns:
            # Bezeichner geprüft, weil sie ins SQL gehen — Spaltennamen können
            # keine Bind-Parameter sein. Konstanten dieser Codebasis, aber die
            # Prüfung kostet nichts und macht die Grenze sichtbar.
            if not IDENTIFIER_PATTERN.match(column):
                raise ExportError(f"{entry.table}.{column!r} ist kein zulässiger Spaltenname.")
            if forbidden_column(column):
                raise ExportError(
                    f"{entry.table}.{column} ist in EXPORT_TABLES eingetragen, "
                    "gehört aber nach der Spaltenregel nicht in einen Export."
                )


async def _read_table(conn: AsyncConnection, schema: str, entry: ExportTable) -> tuple[bytes, int]:
    """Eine Tabelle als CSV-Bytes plus Zeilenzahl."""
    columns = ", ".join(f'"{c}"' for c in entry.columns)
    order = f'"{entry.order_by}"' if entry.order_by in entry.columns else f'"{entry.columns[0]}"'
    # scope-bypass: Ein Export ist der ganze Mandant. Der Schema-Name ist die
    # Grenze — er kommt aus der Registry und ist gegen IDENTIFIER_PATTERN
    # geprüft; eine school_id-Einschränkung wäre hier sachlich falsch.
    stmt = f"SELECT {columns} FROM {_qualified(schema, entry.table)} ORDER BY {order}"
    result = await conn.stream(text(stmt))
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer, delimiter=CSV_DELIMITER, lineterminator="\r\n")
    writer.writerow(entry.columns)
    rows = 0
    async for row in result:
        writer.writerow([_cell(value) for value in row])
        rows += 1
    return buffer.getvalue().encode(CSV_ENCODING), rows


async def _read_templates(conn: AsyncConnection, schema: str) -> list[dict[str, Any]]:
    """Vorlagentexte als eigene Dateien (ADR-0016 D7).

    Ein mehrere Kilobyte langes HTML in einer CSV-Zelle ist formal korrekt und
    praktisch unbrauchbar — kein Tabellenprogramm zeigt es, und beim
    Zurückschreiben zerlegt es die Datei. Deshalb je Vorlage eine Datei.
    """
    # scope-bypass: siehe _read_table.
    stmt = (
        "SELECT id, key, language, school_id, body_html FROM "
        f"{_qualified(schema, 'document_templates')} ORDER BY id"
    )
    files: list[dict[str, Any]] = []
    result = await conn.stream(text(stmt))
    async for row in result:
        template_id, key, language, school_id, body = row
        stem = SAFE_FILENAME.sub("_", f"{key}-{language}")
        if school_id is not None:
            stem = f"{stem}-schule{int(school_id)}"
        files.append(
            {
                "path": f"vorlagen/{stem}.html",
                "template_id": int(template_id),
                "key": str(key),
                "language": str(language),
                "school_id": None if school_id is None else int(school_id),
                "content": (body or "").encode("utf-8"),
            }
        )
    return files


async def _schema_version(conn: AsyncConnection, schema: str) -> str | None:
    stmt = f"SELECT version_num FROM {_qualified(schema, 'alembic_version')}"
    value = (await conn.execute(text(stmt))).scalar()
    return None if value is None else str(value)


def _column_spec(entry: ExportTable) -> list[dict[str, str]]:
    spec: list[dict[str, str]] = []
    for column in entry.columns:
        item = {"name": column}
        note = COLUMN_NOTES.get(column)
        if note:
            item["note"] = note
        spec.append(item)
    return spec


def _readme(slug: str, name: str, generated: datetime) -> str:
    """Kurzanleitung in der Sprache, in der wir mit unseren Kunden reden.

    Nur Deutsch. Für einen französisch- oder italienischsprachigen Kunden ist
    das eine offene Lücke und keine Absicht — sie steht in
    docs/features/multitenancy.md.
    """
    return f"""Export aus Magister
===================

Kunde:      {name} ({slug})
Erstellt:   {generated.isoformat()}
Format:     Version {FORMAT_VERSION}

Was hier drin ist
-----------------
  MANIFEST.json      Beschreibung jeder Datei und jeder Spalte. Die
                     verbindliche Auskunft — auch darüber, was NICHT
                     enthalten ist und warum.
  daten/*.csv        Eine Datei je Tabelle.
  vorlagen/*.html    Der Text jeder Dokumentvorlage als eigene Datei.
  PRUEFSUMMEN.sha256 SHA-256 je Datei.

Die CSV-Dateien lesen
---------------------
Trennzeichen ist das Semikolon, die Kodierung UTF-8 mit BOM. In Excel unter
Windows genügt ein Doppelklick. In einem Programm:

    import csv
    with open("daten/schools.csv", encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f, delimiter=";"):
            print(row["name"])

Konventionen in den Werten:
  * Leeres Feld     = kein Wert (NULL), nicht der leere Text.
  * Zeitstempel     = ISO 8601 mit Zeitzone, z. B. 2026-09-09T03:15:00+00:00.
  * Wahrheitswerte  = true / false.
  * Listen und JSON = JSON in einem Feld, z. B. ["Gruppe A","Gruppe B"].

Wie die Dateien zusammenhängen
------------------------------
Personen werden über ad_object_guid verknüpft, nicht über den Namen: der
objectGUID aus dem Active Directory bleibt gleich, wenn jemand heiratet oder
die Schule wechselt. Klassen, Abteilungen und Geräte hängen über
school_id / class_id / department_id an schools.csv, classes.csv und
departments.csv.

Zuordnungen sind historisiert: valid_from / valid_to. Ein leeres valid_to
heisst „läuft noch“. Beendete Zuordnungen werden nicht gelöscht — die
Geschichte einer Klasse bleibt damit nachvollziehbar.

Prüfen, ob der Export vollständig ist
-------------------------------------
    sha256sum -c PRUEFSUMMEN.sha256

Was nicht enthalten ist
-----------------------
Siehe MANIFEST.json, Abschnitt not_included. Kurz: Anmeldesitzungen,
Notfallzugänge, die Konfiguration der Installation und die verschlüsselten
Audit-Inhalte. Die Audit-Ereignisse selbst (wer, wann, was) sind enthalten.
"""


async def create_export(
    *,
    dsn: str,
    schema_name: str,
    slug: str,
    tenant_name: str,
    export_root: Path,
    when: datetime | None = None,
) -> ExportArtifact:
    """Export als ZIP schreiben und Prüfsumme bilden.

    ZIP und nicht tar.gz: der Empfänger öffnet es unter Windows ohne
    Zusatzprogramm. Deflate, weil CSV sich gut packt und ein Export mit
    Personendaten einer Gemeinde auch mehrere hundert Megabyte haben kann.
    """
    _check_plan()
    # Bezeichner **vor** dem Verbindungsaufbau prüfen. Sonst ist die erste
    # Fehlermeldung bei einem manipulierten Schemanamen eine über die
    # Datenbankverbindung — und die verdeckt, dass die Eingabe das Problem war.
    for value, field in ((slug, "slug"), (schema_name, "schema_name")):
        if not IDENTIFIER_PATTERN.match(value):
            raise ExportError(f"{field}={value!r} ist kein zulässiger Bezeichner.")
    generated = when or datetime.now(UTC)
    stamp = generated.strftime("%Y%m%dT%H%M%SZ")
    directory = export_root / slug
    directory.mkdir(parents=True, exist_ok=True)
    # 0700 auf dem Verzeichnis: hier liegt der einzige Klartext.
    os.chmod(directory, 0o700)
    target = directory / f"{slug}-export-{stamp}.zip"
    partial = target.with_suffix(".zip.partial")

    engine = create_async_engine(dsn)
    try:
        async with engine.connect() as conn:
            schema_version = await _schema_version(conn, schema_name)
            tables: list[tuple[ExportTable, bytes, int]] = []
            for entry in EXPORT_TABLES:
                payload, rows = await _read_table(conn, schema_name, entry)
                tables.append((entry, payload, rows))
            templates = await _read_templates(conn, schema_name)
    except ExportError:
        raise
    except Exception as exc:
        raise ExportError(f"Export gescheitert beim Lesen: {type(exc).__name__}: {exc}") from exc
    finally:
        await engine.dispose()

    files: list[dict[str, Any]] = []
    checksums: list[tuple[str, str]] = []
    row_counts: dict[str, int] = {}

    fd = os.open(partial, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with (
            os.fdopen(fd, "wb") as raw,
            zipfile.ZipFile(raw, "w", compression=zipfile.ZIP_DEFLATED) as archive,
        ):
            for entry, payload, rows in tables:
                path = f"daten/{entry.table}.csv"
                archive.writestr(path, payload)
                digest = hashlib.sha256(payload).hexdigest()
                checksums.append((path, digest))
                row_counts[entry.table] = rows
                files.append(
                    {
                        "path": path,
                        "table": entry.table,
                        "rows": rows,
                        "sha256": digest,
                        "description": entry.description,
                        "columns": _column_spec(entry),
                    }
                )
            for template in templates:
                path = str(template["path"])
                content: bytes = template["content"]
                archive.writestr(path, content)
                digest = hashlib.sha256(content).hexdigest()
                checksums.append((path, digest))
                files.append(
                    {
                        "path": path,
                        "kind": "document_template",
                        "template_id": template["template_id"],
                        "key": template["key"],
                        "language": template["language"],
                        "school_id": template["school_id"],
                        "sha256": digest,
                        "description": "Text einer Dokumentvorlage (HTML).",
                    }
                )

            manifest = {
                "format_version": FORMAT_VERSION,
                "generated_at": generated.isoformat(),
                "tenant": {"slug": slug, "name": tenant_name},
                "schema_version": schema_version,
                "csv": {
                    "delimiter": CSV_DELIMITER,
                    "encoding": CSV_ENCODING,
                    "line_terminator": "\\r\\n",
                    "quoting": "minimal, Anführungszeichen verdoppelt (RFC 4180)",
                    "null": "leeres Feld",
                    "boolean": "true / false",
                    "timestamp": "ISO 8601 mit Zeitzone",
                    "list_and_json": "JSON in einem Feld",
                },
                "join_keys": {
                    "person": "ad_object_guid (objectGUID aus dem AD, stabil)",
                    "school": "school_id -> schools.id",
                    "class": "class_id -> classes.id",
                    "department": "department_id -> departments.id",
                },
                "history": (
                    "Zuordnungen tragen valid_from/valid_to. Leeres valid_to heisst "
                    "„läuft noch“; beendete Zuordnungen bleiben stehen."
                ),
                "files": files,
                "not_included": [
                    {"table": table, "reason": reason}
                    for table, reason in sorted(NOT_EXPORTED.items())
                ],
            }
            manifest_bytes = json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8")
            archive.writestr("MANIFEST.json", manifest_bytes)
            checksums.append(("MANIFEST.json", hashlib.sha256(manifest_bytes).hexdigest()))

            readme = _readme(slug, tenant_name, generated).encode("utf-8")
            archive.writestr("README.txt", readme)
            checksums.append(("README.txt", hashlib.sha256(readme).hexdigest()))

            # Im sha256sum-Format, damit `sha256sum -c` es prüfen kann.
            sums = "".join(f"{digest}  {path}\n" for path, digest in sorted(checksums))
            archive.writestr("PRUEFSUMMEN.sha256", sums.encode("utf-8"))
    except Exception:
        partial.unlink(missing_ok=True)
        raise

    size = partial.stat().st_size
    digest = _sha256_file(partial)
    partial.replace(target)
    os.chmod(target, 0o600)
    logger.info("Export für %s geschrieben: %s (%d Bytes)", slug, target.name, size)
    return ExportArtifact(
        path=target, size_bytes=size, checksum_sha256=digest, row_counts=row_counts
    )


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def expired_exports(root: Path, *, now: datetime | None = None, ttl_days: int) -> Sequence[Path]:
    """Exporte, deren Frist abgelaufen ist.

    Getrennt vom Löschen: wer aufräumt, entscheidet die Betriebsumgebung. Auf
    dem Backup-Share darf Magister nicht löschen (ADR-0016 D2) — das
    Exportverzeichnis ist ein anderes, und hier ist Löschen richtig, weil ein
    liegen gebliebener Export Klartext ist.
    """
    if not root.is_dir():
        return []
    moment = now or datetime.now(UTC)
    cutoff = moment.timestamp() - ttl_days * 86400
    return [path for path in sorted(root.glob("*/*-export-*.zip")) if path.stat().st_mtime < cutoff]


__all__ = [
    "CSV_DELIMITER",
    "CSV_ENCODING",
    "FORMAT_VERSION",
    "ExportArtifact",
    "ExportError",
    "create_export",
    "expired_exports",
]
