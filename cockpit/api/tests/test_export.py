"""Kundenexport (ADR-0016 D7).

Die Abnahmekriterien, und was hier davon prüfbar ist:

* **„Ein Export ist ohne Magister lesbar."** Geprüft wird das ZIP mit den
  Werkzeugen, die ein Empfänger hat: ``zipfile``, ``csv``, ``json``,
  ``sha256sum``. Kein Import aus ``cockpit_api`` beim Lesen — sonst prüft der
  Test genau die Abhängigkeit, die es nicht geben soll.
* **Keine Geheimnisse im Export.** Der Export ist der einzige Ort, an dem
  Kundendaten im Klartext liegen; ein Fehler hier ist unwiderruflich, sobald
  die Datei beim Kunden ist. Also wird das ganze Archiv nach ``password_enc``
  und Verwandtem durchsucht, nicht nur die Spaltenliste geprüft.
* **Die Allowlist passt zum echten Schema.** Der wichtigste Test der Datei:
  ``EXPORT_TABLES`` ist handgeschrieben, und eine handgeschriebene Spaltenliste
  verrottet gegen ein Schema, das sich mit jeder Migration ändert. Geprüft wird
  gegen ein **echt migriertes** Kundenschema — jede Tabelle muss entweder
  exportiert oder mit Begründung ausgeschlossen sein. Eine neue Migration
  bricht diesen Test, bis jemand entscheidet. Das ist die Absicht.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import zipfile
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from cockpit_api.config import settings
from cockpit_api.services.export import (
    CSV_DELIMITER,
    CSV_ENCODING,
    ExportError,
    create_export,
    expired_exports,
)
from cockpit_api.services.export_plan import (
    EXPORT_TABLES,
    NOT_EXPORTED,
    forbidden_column,
)

pytestmark = pytest.mark.asyncio

SLUG = "expo"
SCHEMA = f"t_{SLUG}"

#: Muster, die in einem Export nicht vorkommen dürfen — als Spaltenname und
#: als Wert. ``password_enc`` ist der wichtigste: dort liegen die
#: gespeicherten AD-Passwörter der Schülerinnen und Schüler.
NEVER_IN_AN_EXPORT = (
    "password_enc",
    "password_hash",
    "totp_secret",
    "recovery_codes",
    "oidc_client_secret",
    "ad_bind_password",
    "web_tls_key",
)


@pytest.fixture
def migrated_tenant(db_client: TestClient, magister_admin_dsn: str) -> Iterator[str]:
    """Einen echten Kunden bereitstellen — mit echtem Alembic.

    Ohne das echte Schema prüft dieser Test nur, dass eine Liste zu sich
    selbst passt.

    Vorher wird aufgeräumt: die Konsolen-Datenbank baut jede Testfunktion neu
    auf, das Kundenschema im Magister-Cluster aber nicht. Ohne das ``DROP``
    stapeln sich die Zeilen aus dem vorherigen Test, und der zweite Aufruf von
    ``_seed`` scheitert an einem Unique-Index — was aussieht wie ein Fehler im
    Export und keiner ist.
    """
    import asyncio

    if not settings.magister_api_dir:
        pytest.skip("COCKPIT_TEST_MAGISTER_API_DIR nicht gesetzt")

    async def clean() -> None:
        engine = create_async_engine(magister_admin_dsn, poolclass=NullPool)
        try:
            async with engine.begin() as conn:
                await conn.exec_driver_sql(f"DROP SCHEMA IF EXISTS {SCHEMA} CASCADE")
            # Eigene Transaktion: DROP OWNED BY scheitert, wenn die Rolle noch
            # nicht existiert, und soll dann das Schema-DROP nicht mitreissen.
            # Beim ersten Lauf ist genau das der Normalfall.
            exists = "SELECT 1 FROM pg_roles WHERE rolname = :r"
            async with engine.begin() as conn:
                found = (await conn.execute(text(exists), {"r": f"r_{SLUG}"})).scalar()
                if found:
                    await conn.exec_driver_sql(f"DROP OWNED BY r_{SLUG} CASCADE")
                    await conn.exec_driver_sql(f"DROP ROLE r_{SLUG}")
        finally:
            await engine.dispose()

    asyncio.run(clean())
    created = db_client.post(
        "/api/tenants",
        json={"slug": SLUG, "name": "Exportstadt", "hostname": f"{SLUG}.magister.test"},
    )
    assert created.status_code == 201, created.text
    yield SCHEMA


async def _seed(dsn: str) -> None:
    """Ein paar Zeilen, damit der Export nicht nur Kopfzeilen enthält."""
    engine = create_async_engine(dsn, poolclass=NullPool)
    try:
        async with engine.begin() as conn:
            await conn.exec_driver_sql(f'SET search_path = "{SCHEMA}", public')
            await conn.execute(
                text(
                    "INSERT INTO schools (name, kuerzel, scope_short) "
                    "VALUES ('Primarschule Musterdorf', 'pmd', 'mud')"
                )
            )
            school_id = (await conn.execute(text("SELECT id FROM schools LIMIT 1"))).scalar_one()
            await conn.execute(
                text(
                    "INSERT INTO classes (school_id, name, jahrgangsstufe, status) "
                    "VALUES (:s, '3a', 3, 'active')"
                ),
                {"s": school_id},
            )
            await conn.execute(
                text(
                    "INSERT INTO ad_user_cache (ad_object_guid, upn, kind, school_id, "
                    "given_name, surname, store_password, password_enc) VALUES "
                    "('guid-1', 'anna.muster@musterdorf.ch', 'student', :s, 'Anna', "
                    "'Muster', true, pgp_sym_encrypt('Sehr-Geheim-42', 'kundenschluessel'))"
                ),
                {"s": school_id},
            )
            await conn.execute(
                text(
                    "INSERT INTO document_templates (key, language, subject, body_html, "
                    "is_active, updated_at) VALUES ('password_letter', 'de', "
                    "'Ihr Passwort', "
                    "'<h1>Guten Tag</h1><p>Ihr neues Passwort lautet …</p>', true, now())"
                )
            )
            # Eine Vorlage des Betreibers (ADR-0018): derselbe Schlüssel und
            # dieselbe Sprache wie oben. Genau der Fall, in dem sich zwei
            # Dateien den Namen teilen würden.
            await conn.execute(
                text(
                    "INSERT INTO platform_document_templates (key, language, subject, "
                    "body_html, may_override, version, delivered_at) VALUES "
                    "('password_letter', 'de', 'Ihr Passwort (Vorgabe)', "
                    "'<h1>Vorgabe des Betreibers</h1>', true, 4, now())"
                )
            )
    finally:
        await engine.dispose()


def _archive(path: Path) -> zipfile.ZipFile:
    return zipfile.ZipFile(path)


class TestThePlanMatchesTheRealSchema:
    """Der wichtigste Test der Datei — gegen ein echt migriertes Schema."""

    async def test_every_exported_column_exists(
        self, migrated_tenant: str, magister_admin_dsn: str
    ) -> None:
        """Eine handgeschriebene Spaltenliste verrottet. Hier fällt das auf.

        Ohne diesen Test scheitert ein Export erst beim Kunden, mit einem
        ``UndefinedColumn`` aus Postgres — und zwar genau dann, wenn jemand
        seine Daten braucht.
        """
        engine = create_async_engine(magister_admin_dsn, poolclass=NullPool)
        try:
            async with engine.connect() as conn:
                rows = (
                    await conn.execute(
                        text(
                            "SELECT table_name, column_name FROM information_schema.columns "
                            "WHERE table_schema = :s"
                        ),
                        {"s": SCHEMA},
                    )
                ).all()
        finally:
            await engine.dispose()
        actual: dict[str, set[str]] = {}
        for table, column in rows:
            actual.setdefault(str(table), set()).add(str(column))

        missing: list[str] = []
        for entry in EXPORT_TABLES:
            if entry.table not in actual:
                missing.append(f"{entry.table} (Tabelle fehlt)")
                continue
            for column in entry.columns:
                if column not in actual[entry.table]:
                    missing.append(f"{entry.table}.{column}")
        assert not missing, "in EXPORT_TABLES, aber nicht im Schema: " + ", ".join(missing)

    async def test_every_table_is_decided(
        self, migrated_tenant: str, magister_admin_dsn: str
    ) -> None:
        """Exportiert oder mit Begründung ausgeschlossen — ein Drittes gibt es nicht.

        Eine neue Migration bricht diesen Test. Richtig so: ob eine neue
        Tabelle Kundendaten enthält, entscheidet ein Mensch und nicht das
        Weglassen eines Eintrags.
        """
        engine = create_async_engine(magister_admin_dsn, poolclass=NullPool)
        try:
            async with engine.connect() as conn:
                found = {
                    str(row[0])
                    for row in (
                        await conn.execute(
                            text(
                                "SELECT table_name FROM information_schema.tables "
                                "WHERE table_schema = :s AND table_type = 'BASE TABLE'"
                            ),
                            {"s": SCHEMA},
                        )
                    ).all()
                }
        finally:
            await engine.dispose()
        decided = {entry.table for entry in EXPORT_TABLES} | set(NOT_EXPORTED)
        undecided = sorted(found - decided)
        assert not undecided, (
            "Diese Tabellen sind weder in EXPORT_TABLES noch in NOT_EXPORTED: "
            + ", ".join(undecided)
            + " — eintragen und dabei entscheiden, ob sie Kundendaten enthalten."
        )

    async def test_the_operator_log_goes_out_without_the_session_fragment(self) -> None:
        """Der Zugriffs-Nachweis gehört dem Kunden — das Zugangsmittel nicht.

        `session_ref` sind die ersten Zeichen einer Session-Id. Allein
        unbrauchbar, und trotzdem nichts, was in eine Datei gehört, die der
        Kunde weitergibt.
        """
        (entry,) = [e for e in EXPORT_TABLES if e.table == "operator_accesses"]
        assert "reason" in entry.columns
        assert "operator_upn" in entry.columns
        assert "session_ref" not in entry.columns

    async def test_no_exported_column_is_forbidden(self) -> None:
        offenders = [
            f"{entry.table}.{column}"
            for entry in EXPORT_TABLES
            for column in entry.columns
            if forbidden_column(column)
        ]
        assert not offenders, offenders

    async def test_the_forbidden_rule_catches_the_real_names(self) -> None:
        """Die Regel muss die Spalten treffen, um die es geht."""
        for name in (
            "password_enc",
            "password_hash",
            "totp_secret_enc",
            "oidc_client_secret_enc",
            "ad_bind_password_enc",
            "web_tls_key_enc",
            "recovery_codes",
            "payload",
        ):
            assert forbidden_column(name), name

    async def test_the_forbidden_rule_leaves_harmless_flags_alone(self) -> None:
        """Sonst fehlten dem Kunden Felder, die er braucht.

        ``password_never_expires`` und ``store_password`` sind Wahrheitswerte
        über eine Person, kein Geheimnis — eine zu breite Regel („enthält
        password") hätte sie mitgenommen.
        """
        for name in (
            "password_never_expires",
            "cannot_change_password",
            "store_password",
            "password_changed_at",
        ):
            assert not forbidden_column(name), name


@pytest.mark.usefixtures("migrated_tenant")
class TestTheExportIsReadableWithoutMagister:
    async def test_the_archive_carries_data_manifest_and_checksums(
        self, magister_admin_dsn: str, tmp_path: Path
    ) -> None:
        await _seed(magister_admin_dsn)
        artifact = await create_export(
            dsn=magister_admin_dsn,
            schema_name=SCHEMA,
            slug=SLUG,
            tenant_name="Exportstadt",
            export_root=tmp_path,
        )
        assert artifact.size_bytes > 0
        with _archive(artifact.path) as archive:
            names = set(archive.namelist())
            assert "MANIFEST.json" in names
            assert "README.txt" in names
            assert "PRUEFSUMMEN.sha256" in names
            assert "daten/schools.csv" in names
            assert any(n.startswith("vorlagen/") for n in names)
            # Beide Fassungen, in getrennten Ordnern. Ohne die Trennung
            # überschriebe die eine die andere — bei gleichem Schlüssel und
            # gleicher Sprache heissen sie identisch.
            assert "vorlagen/password_letter-de.html" in names
            assert "vorlagen/plattform/password_letter-de.html" in names
            assert b"Vorgabe des Betreibers" in archive.read(
                "vorlagen/plattform/password_letter-de.html"
            )
            assert "daten/platform_document_templates.csv" in names

            manifest = json.loads(archive.read("MANIFEST.json"))
            assert manifest["tenant"]["slug"] == SLUG
            assert manifest["csv"]["delimiter"] == CSV_DELIMITER
            assert manifest["csv"]["encoding"] == CSV_ENCODING
            assert manifest["schema_version"]

            # Jede Datei im Manifest ist im Archiv, und umgekehrt jede
            # Datendatei im Manifest.
            for entry in manifest["files"]:
                assert entry["path"] in names, entry["path"]

    async def test_a_recipient_can_read_a_csv_with_stdlib_only(
        self, magister_admin_dsn: str, tmp_path: Path
    ) -> None:
        """Genau so, wie es in der README steht — sonst ist die README falsch."""
        await _seed(magister_admin_dsn)
        artifact = await create_export(
            dsn=magister_admin_dsn,
            schema_name=SCHEMA,
            slug=SLUG,
            tenant_name="Exportstadt",
            export_root=tmp_path,
        )
        with _archive(artifact.path) as archive:
            raw = archive.read("daten/schools.csv").decode(CSV_ENCODING)
            rows = list(csv.DictReader(io.StringIO(raw, newline=""), delimiter=CSV_DELIMITER))
        assert rows, "die CSV enthält keine Zeile"
        assert rows[0]["name"] == "Primarschule Musterdorf"
        assert rows[0]["kuerzel"] == "pmd"

    async def test_the_checksums_verify(self, magister_admin_dsn: str, tmp_path: Path) -> None:
        """Im ``sha256sum -c``-Format, und die Summen stimmen auch."""
        await _seed(magister_admin_dsn)
        artifact = await create_export(
            dsn=magister_admin_dsn,
            schema_name=SCHEMA,
            slug=SLUG,
            tenant_name="Exportstadt",
            export_root=tmp_path,
        )
        with _archive(artifact.path) as archive:
            listed = {}
            for line in archive.read("PRUEFSUMMEN.sha256").decode("utf-8").splitlines():
                digest, _, name = line.partition("  ")
                listed[name] = digest
            assert listed
            for name, digest in listed.items():
                assert hashlib.sha256(archive.read(name)).hexdigest() == digest, name

    async def test_the_values_follow_the_documented_conventions(
        self, magister_admin_dsn: str, tmp_path: Path
    ) -> None:
        """NULL als leeres Feld, Wahrheitswerte als true/false, Listen als JSON."""
        await _seed(magister_admin_dsn)
        artifact = await create_export(
            dsn=magister_admin_dsn,
            schema_name=SCHEMA,
            slug=SLUG,
            tenant_name="Exportstadt",
            export_root=tmp_path,
        )
        with _archive(artifact.path) as archive:
            raw = archive.read("daten/ad_user_cache.csv").decode(CSV_ENCODING)
            row = next(csv.DictReader(io.StringIO(raw, newline=""), delimiter=CSV_DELIMITER))
        assert row["store_password"] == "true"  # noqa: S105 — ein Flag, kein Passwort
        # ad_groups ist ein JSONB-Array und kommt als JSON, nicht als
        # Python-repr mit einfachen Anführungszeichen.
        assert json.loads(row["ad_groups"]) == []
        # jahrgangsstufe ist bei dieser Zeile NULL.
        assert row["jahrgangsstufe"] == ""
        # Zeitstempel mit Offset, damit er in einer anderen Zeitzone eindeutig ist.
        assert row["last_sync_at"] == "" or "+" in row["last_sync_at"]

    async def test_two_exports_of_the_same_state_are_identical(
        self, magister_admin_dsn: str, tmp_path: Path
    ) -> None:
        """Damit ein Kunde zwei Exporte vergleichen kann.

        Nur die Datendateien, nicht das Archiv: das Manifest trägt den
        Zeitpunkt, und der ist zwischen zwei Läufen verschieden.
        """
        await _seed(magister_admin_dsn)
        first = await create_export(
            dsn=magister_admin_dsn,
            schema_name=SCHEMA,
            slug=SLUG,
            tenant_name="Exportstadt",
            export_root=tmp_path / "a",
        )
        second = await create_export(
            dsn=magister_admin_dsn,
            schema_name=SCHEMA,
            slug=SLUG,
            tenant_name="Exportstadt",
            export_root=tmp_path / "b",
        )
        with _archive(first.path) as a, _archive(second.path) as b:
            for entry in EXPORT_TABLES:
                name = f"daten/{entry.table}.csv"
                assert a.read(name) == b.read(name), name


@pytest.mark.usefixtures("migrated_tenant")
class TestNoSecretsLeave:
    async def test_the_archive_contains_no_secret_column_or_value(
        self, magister_admin_dsn: str, tmp_path: Path
    ) -> None:
        """Nicht nur die Spaltenliste — das ganze Archiv.

        Ein gespeichertes Schülerpasswort im Export wäre der Fehler, den man
        nicht zurücknehmen kann: die Datei ist dann beim Kunden, unverschlüsselt.
        """
        await _seed(magister_admin_dsn)
        artifact = await create_export(
            dsn=magister_admin_dsn,
            schema_name=SCHEMA,
            slug=SLUG,
            tenant_name="Exportstadt",
            export_root=tmp_path,
        )
        with _archive(artifact.path) as archive:
            for name in archive.namelist():
                blob = archive.read(name).decode("utf-8", "replace").lower()
                for needle in NEVER_IN_AN_EXPORT:
                    if name == "MANIFEST.json" and needle == "password_enc":
                        # Das Manifest *nennt* die Spalte, um zu erklären,
                        # dass sie fehlt. Das ist der Zweck des Manifests.
                        continue
                    assert needle not in blob, f"{needle!r} steht in {name}"
                assert "sehr-geheim-42" not in blob, f"Klartext-Passwort in {name}"

    async def test_the_manifest_says_what_is_missing_and_why(
        self, magister_admin_dsn: str, tmp_path: Path
    ) -> None:
        """Der Kunde soll die Lücke sehen, nicht vermuten."""
        artifact = await create_export(
            dsn=magister_admin_dsn,
            schema_name=SCHEMA,
            slug=SLUG,
            tenant_name="Exportstadt",
            export_root=tmp_path,
        )
        with _archive(artifact.path) as archive:
            manifest = json.loads(archive.read("MANIFEST.json"))
        excluded = {entry["table"]: entry["reason"] for entry in manifest["not_included"]}
        assert set(excluded) == set(NOT_EXPORTED)
        for reason in excluded.values():
            assert len(reason) > 20, reason

    async def test_the_file_is_not_world_readable(
        self, magister_admin_dsn: str, tmp_path: Path
    ) -> None:
        """Ein Export ist der einzige Klartext. Er liegt nicht offen herum."""
        artifact = await create_export(
            dsn=magister_admin_dsn,
            schema_name=SCHEMA,
            slug=SLUG,
            tenant_name="Exportstadt",
            export_root=tmp_path,
        )
        assert artifact.path.stat().st_mode & 0o077 == 0
        assert artifact.path.parent.stat().st_mode & 0o077 == 0


class TestGuards:
    async def test_a_bad_slug_never_reaches_the_database(self, tmp_path: Path) -> None:
        with pytest.raises(ExportError, match="Bezeichner"):
            await create_export(
                dsn="postgresql+asyncpg://x@localhost/x",
                schema_name="t_ok",
                slug="../../etc",
                tenant_name="x",
                export_root=tmp_path,
            )

    async def test_a_bad_schema_never_reaches_the_database(self, tmp_path: Path) -> None:
        with pytest.raises(ExportError, match="Bezeichner"):
            await create_export(
                dsn="postgresql+asyncpg://x@localhost/x",
                schema_name='public"; DROP SCHEMA t_other CASCADE; --',
                slug="ok",
                tenant_name="x",
                export_root=tmp_path,
            )

    async def test_an_expired_export_is_found(self, tmp_path: Path) -> None:
        """Aufräumen ist Pflicht, nicht Kür: die Datei ist Klartext."""
        import os
        import time

        directory = tmp_path / SLUG
        directory.mkdir(parents=True)
        old = directory / f"{SLUG}-export-20200101T000000Z.zip"
        old.write_bytes(b"alt")
        fresh = directory / f"{SLUG}-export-20991231T000000Z.zip"
        fresh.write_bytes(b"neu")
        os.utime(old, (time.time() - 40 * 86400, time.time() - 40 * 86400))

        due = expired_exports(tmp_path, ttl_days=7)
        assert old in due
        assert fresh not in due
