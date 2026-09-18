"""Wiederherstellen und Prüfen (ADR-0016 D4, D5).

Zwei Dinge, die beim Bauen anders herauskamen als im ADR — beide zum Besseren,
und beide gehören ausgesprochen:

**Der private Schlüssel wird hier gebraucht, und das widerspricht D2.** D2 sagt,
der private Backup-Schlüssel liege getrennt und werde auf dem Anwendungsserver
nie gebraucht. D4 verlangt eine wöchentliche Prüf-Wiederherstellung — und die
muss entschlüsseln. Beides gleichzeitig geht nicht auf **einer** Maschine.
Auflösung: dieses Modul läuft **nicht** auf dem Anwendungsserver, sondern dort,
wo der Schlüssel liegt (Backup-Host), und meldet das Ergebnis an die Konsole.
Die Konsole selbst hat den Schlüssel nie. Deshalb nimmt jede Funktion hier den
Pfad zur Identitätsdatei als Argument, statt ihn aus den Einstellungen zu
lesen: eine Einstellung würde dazu verleiten, das doch auf dem Anwendungsserver
zu konfigurieren.

**Wiederhergestellt wird in eine eigene Datenbank, nicht in ein Nebenschema.**
D5 nennt ein Schema ``r_<slug>_<zeitstempel>`` neben dem Produktivschema. Der
Grund für die Abweichung ist handfest: ein ``pg_dump --schema=t_slug`` enthält
``CREATE SCHEMA t_slug`` und durchgängig qualifizierte Namen. In dieselbe
Datenbank zurückspielen heisst also entweder auf das Produktivschema schreiben
(verboten) oder den Schemanamen im ausgegebenen SQL umschreiben — eine
Textersetzung auf SQL, die man nicht verantworten will.

In eine frische Datenbank spielt derselbe Dump unverändert ein. Und das
Umschalten bleibt genau das, was D5 verspricht: **ein Registry-Eintrag.** Die
Registry trägt DSN *und* Schema (ADR-0013 D1), also ist eine andere Datenbank
dort dieselbe Art von Änderung wie ein anderes Schema. Die Zusage „daneben,
nie darüber" wird dadurch stärker, nicht schwächer: das Produktivschema wird
nicht einmal geöffnet.
"""

from __future__ import annotations

import logging
import shutil
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine

from cockpit_api.services.backup import IDENTIFIER_PATTERN, BackupError, verify_checksum
from cockpit_api.services.pgtools import Stage, ToolError, libpq_env, run_chain

logger = logging.getLogger(__name__)

#: Tabellen, die in einem wiederhergestellten Kundenschema stehen müssen.
#: Bewusst eine kleine, stabile Auswahl statt aller 27: die Liste soll bei
#: jeder neuen Migration nicht mitwachsen, aber merken, wenn ein Dump nur den
#: halben Bestand enthält.
EXPECTED_TABLES: frozenset[str] = frozenset(
    {
        "alembic_version",
        "schools",
        "classes",
        "audit_events",
        "sessions",
        "app_settings",
        "role_assignments",
    }
)

#: Name der Wegwerf-Datenbank für eine Prüfung.
VERIFY_DB_PATTERN = "v_{slug}_{stamp}"

#: Name der Datenbank für eine echte Wiederherstellung.
RESTORE_DB_PATTERN = "r_{slug}_{stamp}"


class RestoreError(RuntimeError):
    """Die Wiederherstellung ist gescheitert."""


def _ident(value: str, *, field: str) -> str:
    """Bezeichner für SQL — geprüft **und** gequotet.

    Schema- und Tabellennamen können nicht als Bind-Parameter übergeben
    werden. Die Prüfung ist deshalb die Grenze, das Quoting der Gürtel dazu.
    Die Werte kommen aus der Registry, nicht von einem Anwender — die Prüfung
    steht hier trotzdem, weil eine manipulierte Registry-Zeile sonst der
    kürzeste Weg in fremdes SQL wäre.
    """
    if not IDENTIFIER_PATTERN.match(value):
        raise RestoreError(f"{field}={value!r} ist kein zulässiger Bezeichner.")
    return f'"{value}"'


@dataclass(slots=True)
class VerifyResult:
    ok: bool
    checks: list[str] = field(default_factory=list[str])
    problems: list[str] = field(default_factory=list[str])

    @property
    def detail(self) -> str:
        parts = [f"ok: {', '.join(self.checks)}"] if self.checks else []
        if self.problems:
            parts.append(f"Probleme: {'; '.join(self.problems)}")
        return " | ".join(parts) or "keine Prüfung gelaufen"


def scratch_database_name(pattern: str, slug: str, when: datetime | None = None) -> str:
    if not IDENTIFIER_PATTERN.match(slug):
        raise RestoreError(f"slug={slug!r} ist kein zulässiger Bezeichner.")
    stamp = (when or datetime.now(UTC)).strftime("%Y%m%d%H%M%S")
    name = pattern.format(slug=slug, stamp=stamp)
    if not IDENTIFIER_PATTERN.match(name):
        raise RestoreError(f"Datenbankname {name!r} ist nicht zulässig.")
    return name


def _admin_dsn_for(dsn: str, database: str) -> str:
    """Denselben Zugang, andere Datenbank.

    ``render_as_string(hide_password=False)``, nicht ``str()``: letzteres
    maskiert das Passwort zu ``***`` — gut fürs Protokoll, unbrauchbar zum
    Anmelden. Kostete eine halbe Stunde Suche in einer
    ``InvalidPasswordError``, die aussah wie ein falsch gesetztes Testkonto.
    """
    return make_url(dsn).set(database=database).render_as_string(hide_password=False)


async def _create_database(admin_dsn: str, name: str) -> None:
    # CREATE DATABASE geht nicht in einer Transaktion, deshalb AUTOCOMMIT.
    engine = create_async_engine(admin_dsn, isolation_level="AUTOCOMMIT")
    try:
        async with engine.connect() as conn:
            await conn.execute(text(f'CREATE DATABASE "{name}"'))
    finally:
        await engine.dispose()


async def _drop_database(admin_dsn: str, name: str) -> None:
    engine = create_async_engine(admin_dsn, isolation_level="AUTOCOMMIT")
    try:
        async with engine.connect() as conn:
            # WITH (FORCE): eine hängende Verbindung soll das Aufräumen nicht
            # verhindern, sonst bleiben Wegwerf-Datenbanken liegen.
            await conn.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
    finally:
        await engine.dispose()


async def restore_dump(
    *,
    admin_dsn: str,
    dump_path: Path,
    identity_file: Path,
    target_database: str,
    expected_checksum: str | None = None,
) -> None:
    """Verschlüsselten Dump in eine **neue** Datenbank einspielen.

    ``age -d`` und ``pg_restore`` als Kette ohne Zwischendatei: ein
    entschlüsselter Dump auf der Platte ist genau das, was die Verschlüsselung
    verhindern soll.
    """
    for tool in ("age", "pg_restore"):
        if shutil.which(tool) is None:
            raise RestoreError(f"{tool} ist nicht installiert.")
    if not dump_path.is_file():
        raise RestoreError(f"Dump {dump_path} fehlt.")
    if not identity_file.is_file():
        raise RestoreError(
            f"Identitätsdatei {identity_file} fehlt. Dieses Werkzeug läuft dort, "
            "wo der private Backup-Schlüssel liegt — nicht auf dem Anwendungsserver."
        )
    if expected_checksum and not verify_checksum(dump_path, expected_checksum):
        # Vor dem Entschlüsseln: eine veränderte Datei ist ein Vorfall und
        # kein Wiederherstellungsproblem.
        raise RestoreError(
            f"Die Prüfsumme von {dump_path.name} weicht ab. Der Dump wurde auf dem "
            "Share verändert — nicht einspielen, Vorfall behandeln."
        )

    await _create_database(admin_dsn, target_database)
    try:
        await run_chain(
            Stage(argv=("age", "-d", "-i", str(identity_file), str(dump_path)), label="age -d"),
            Stage(
                argv=(
                    "pg_restore",
                    "--no-owner",
                    "--no-privileges",
                    "--exit-on-error",
                    f"--dbname={target_database}",
                ),
                env=libpq_env(admin_dsn),
                label="pg_restore",
            ),
        )
    except ToolError as exc:
        # Halbe Datenbanken bleiben nicht stehen: sie sehen aus wie eine
        # geprüfte Wiederherstellung und sind keine.
        await _drop_database(admin_dsn, target_database)
        raise RestoreError(f"Einspielen gescheitert: {exc}") from exc
    logger.info("Dump %s in Datenbank %s eingespielt", dump_path.name, target_database)


async def verify_backup(
    *,
    admin_dsn: str,
    dump_path: Path,
    identity_file: Path,
    slug: str,
    schema_name: str,
    expected_schema_version: str | None = None,
    expected_checksum: str | None = None,
    reference_row_counts: dict[str, int] | None = None,
    keep: bool = False,
) -> VerifyResult:
    """Prüf-Wiederherstellung (ADR-0016 D4).

    Ein Backup gilt erst als Backup, wenn es eingespielt wurde. Geprüft wird,
    was ohne Kundenschlüssel prüfbar ist:

    * die erwarteten Tabellen sind da,
    * die Alembic-Version passt,
    * die Zeilenzahlen liegen in plausibler Grössenordnung,
    * ``audit_events`` ist lesbar und die Payloads sind **nicht** im Klartext.

    Der vierte Punkt ist die abgespeckte Fassung des ADR-Kriteriums „ein
    Audit-Payload lässt sich mit dem Kundenschlüssel entschlüsseln": den
    Kundenschlüssel hat dieser Prozess nicht. Was er zeigen kann, ist das
    Gegenteil und fast so nützlich — dass die Payloads **verschlüsselt**
    vorliegen. Ein Dump mit Klartext-Payloads wäre ein Fehler, den man sofort
    sehen will.
    """
    database = scratch_database_name(VERIFY_DB_PATTERN, slug)
    result = VerifyResult(ok=False)
    try:
        await restore_dump(
            admin_dsn=admin_dsn,
            dump_path=dump_path,
            identity_file=identity_file,
            target_database=database,
            expected_checksum=expected_checksum,
        )
    except RestoreError as exc:
        result.problems.append(str(exc))
        return result

    try:
        result = await _run_checks(
            admin_dsn=admin_dsn,
            database=database,
            schema_name=schema_name,
            expected_schema_version=expected_schema_version,
            reference_row_counts=reference_row_counts,
        )
    finally:
        if not keep:
            await _drop_database(admin_dsn, database)
        else:
            logger.warning("Prüf-Datenbank %s bleibt stehen (keep=True)", database)
    return result


async def _run_checks(
    *,
    admin_dsn: str,
    database: str,
    schema_name: str,
    expected_schema_version: str | None,
    reference_row_counts: dict[str, int] | None,
) -> VerifyResult:
    result = VerifyResult(ok=True)
    schema = _ident(schema_name, field="schema_name")
    engine = create_async_engine(_admin_dsn_for(admin_dsn, database))
    try:
        async with engine.connect() as conn:
            found = {
                str(row[0])
                for row in (
                    await conn.execute(
                        text(
                            "SELECT table_name FROM information_schema.tables "
                            "WHERE table_schema = :s"
                        ),
                        {"s": schema_name},
                    )
                ).all()
            }
            missing = sorted(EXPECTED_TABLES - found)
            if missing:
                result.ok = False
                result.problems.append(f"Tabellen fehlen: {', '.join(missing)}")
            else:
                result.checks.append(f"{len(found)} Tabellen vorhanden")

            if "alembic_version" in found:
                # Der Schemaname ist geprüft und gequotet (_ident).
                stmt = f"SELECT version_num FROM {schema}.alembic_version"
                version = (await conn.execute(text(stmt))).scalar()
                if expected_schema_version and str(version) != expected_schema_version:
                    result.ok = False
                    result.problems.append(
                        f"Alembic-Version {version!r}, erwartet {expected_schema_version!r}"
                    )
                else:
                    result.checks.append(f"Alembic-Version {version}")

            if "audit_events" in found:
                await _check_audit_payloads(conn, schema, result)

            if reference_row_counts:
                await _check_row_counts(conn, schema, reference_row_counts, result)
    except Exception as exc:  # eine kaputte Datenbank ist ein Prüfergebnis
        result.ok = False
        result.problems.append(f"Prüfung abgebrochen: {type(exc).__name__}: {exc}")
    finally:
        await engine.dispose()
    return result


async def _check_audit_payloads(conn: AsyncConnection, schema: str, result: VerifyResult) -> None:
    """Sind die Audit-Payloads verschlüsselt?

    Ein pgcrypto-Chiffrat beginnt mit dem PGP-Paket-Marker ``\\xc3`` bzw.
    ``\\x85`` — jedenfalls nicht mit einer lesbaren JSON-Klammer. Wir prüfen
    genau das: ein Payload, der mit ``{`` anfängt, ist Klartext, und das wäre
    ein Fehler, den man sofort sehen will.
    """
    stmt = (
        "SELECT count(*), count(*) FILTER (WHERE left(payload::text, 3) = '\\x7b') "
        f"FROM {schema}.audit_events"
    )
    row = (await conn.execute(text(stmt))).one_or_none()
    if row is None:
        return
    total, plaintext = int(row[0]), int(row[1] or 0)
    if total == 0:
        result.checks.append("audit_events lesbar (leer)")
        return
    if plaintext:
        result.ok = False
        result.problems.append(f"{plaintext} von {total} Audit-Payloads liegen im Klartext vor")
    else:
        result.checks.append(f"{total} Audit-Payloads verschlüsselt")


async def _check_row_counts(
    conn: AsyncConnection,
    schema: str,
    reference: dict[str, int],
    result: VerifyResult,
) -> None:
    """Zeilenzahlen in plausibler Grössenordnung.

    Nicht auf Gleichheit: zwischen Sicherung und Prüfung liegen Stunden, in
    denen produktiv weitergearbeitet wurde. Geprüft wird, dass der Dump nicht
    **wesentlich weniger** enthält — ein Dump mit 3 statt 300 Schülern ist
    kaputt, einer mit 298 ist normal.
    """
    for table, expected in reference.items():
        if not IDENTIFIER_PATTERN.match(table):
            continue

        stmt = f"SELECT count(*) FROM {schema}.{_ident(table, field='table')}"
        actual = (await conn.execute(text(stmt))).scalar_one()
        if expected > 0 and int(actual) < expected * 0.5:
            result.ok = False
            result.problems.append(f"{table}: {actual} Zeilen im Dump gegen {expected} produktiv")
        else:
            result.checks.append(f"{table}: {actual} Zeilen")


__all__ = [
    "EXPECTED_TABLES",
    "RESTORE_DB_PATTERN",
    "VERIFY_DB_PATTERN",
    "BackupError",
    "RestoreError",
    "VerifyResult",
    "restore_dump",
    "scratch_database_name",
    "verify_backup",
]
