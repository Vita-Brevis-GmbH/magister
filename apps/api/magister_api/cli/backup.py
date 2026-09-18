"""``magister-cli backup verify`` für eine Einzelinstallation (ADR-0016 D9).

Ein Backup gilt erst als Backup, wenn es eingespielt wurde. Auf einer
Einzelinstallation gibt es keine Konsole und keinen Backup-Host — also macht
es dieses Werkzeug: Prüfsumme nachrechnen, in eine **Wegwerf-Datenbank**
einspielen, prüfen, wieder verwerfen.

    magister-cli backup verify --dump … --identity … --admin-dsn …

**Warum das hier steht und nicht in der Konsole wiederverwendet wird:** die
Datenebene darf nicht von der Konsole abhängen — eine Gemeinde mit einem
Server soll keinen Plattform-Betrieb mitinstallieren (ADR-0016 D9). Die
gehostete Variante hat ihre eigene Fassung in
``cockpit_api/cli/verify_backup.py``, die zusätzlich pro Kundenschema arbeitet
und das Ergebnis an die Konsole meldet. Zwei kleine Fassungen sind hier
billiger als eine gemeinsame Abhängigkeit in die falsche Richtung — und der
Umfang ist klein genug, dass sie nicht auseinanderlaufen: was hier geprüft
wird, steht in ``EXPECTED_TABLES``.

Der **private** Schlüssel wird gebraucht. Dieses Werkzeug läuft deshalb dort,
wo er liegt, und der Pfad ist ein Argument und keine Einstellung — eine
Einstellung würde dazu verleiten, ihn doch auf dem Anwendungsserver zu
hinterlegen.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import logging
import os
import re
import shutil
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine

from magister_api.cli._pipe import PipeError, Stage, run_pipe

logger = logging.getLogger("magister.backup")

#: Tabellen, die in einer brauchbaren Sicherung stehen müssen. Bewusst eine
#: kleine, stabile Auswahl statt aller 27: die Liste soll bei jeder neuen
#: Migration nicht mitwachsen, aber merken, wenn ein Dump nur den halben
#: Bestand enthält.
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

#: Name der Wegwerf-Datenbank. Eng geprüft, weil er in ein ``CREATE DATABASE``
#: geht und dort keine Bind-Parameter möglich sind.
DB_NAME = re.compile(r"^[a-z][a-z0-9_]{0,62}$")


class BackupVerifyError(RuntimeError):
    """Die Prüfung liess sich nicht durchführen."""


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


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def libpq_env(dsn: str) -> dict[str, str]:
    """libpq-Umgebung aus einem DSN. Passwort über ``PGPASSWORD``, nie über argv.

    argv ist auf einem Mehrbenutzersystem für jeden in ``ps`` sichtbar; die
    Umgebung eines fremden Prozesses ist es nicht.
    """
    url = make_url(dsn)
    env = dict(os.environ)
    if url.host:
        env["PGHOST"] = url.host
    if url.port:
        env["PGPORT"] = str(url.port)
    if url.username:
        env["PGUSER"] = url.username
    if url.password:
        env["PGPASSWORD"] = url.password
    return env


def _decrypt_and_restore(*, dump: Path, identity: Path, database: str, admin_dsn: str) -> None:
    """``age -d | pg_restore`` als Kette ohne Zwischendatei.

    Ohne Zwischendatei, weil ein entschlüsselter Dump auf der Platte genau das
    ist, was die Verschlüsselung verhindern soll. Die Mechanik der Kette
    (beide Pipe-Enden schliessen, ``stderr`` in Dateien, absolute Pfade) steht
    in ``cli/_pipe.py`` und nicht hier: sie wird auch für ``pg_dump | age``
    beim Vor-Migrations-Dump gebraucht, und zweimal dieselben drei Fallen zu
    umgehen ist einmal zu viel.
    """
    age_bin = shutil.which("age")
    restore_bin = shutil.which("pg_restore")
    if age_bin is None or restore_bin is None:  # pragma: no cover - _preflight prüft das
        raise BackupVerifyError("age oder pg_restore ist nicht installiert.")
    try:
        run_pipe(
            Stage(argv=(age_bin, "-d", "-i", str(identity), str(dump)), label="age -d"),
            Stage(
                argv=(
                    restore_bin,
                    "--no-owner",
                    "--no-privileges",
                    "--exit-on-error",
                    f"--dbname={database}",
                ),
                env=libpq_env(admin_dsn),
                label="pg_restore",
            ),
        )
    except PipeError as exc:
        raise BackupVerifyError(str(exc)) from exc


async def _create_database(admin_dsn: str, name: str) -> None:
    # CREATE DATABASE geht nicht in einer Transaktion, deshalb AUTOCOMMIT.
    engine = create_async_engine(admin_dsn, isolation_level="AUTOCOMMIT")
    try:
        async with engine.connect() as conn:
            await conn.exec_driver_sql(f'CREATE DATABASE "{name}"')
    finally:
        await engine.dispose()


async def _drop_database(admin_dsn: str, name: str) -> None:
    engine = create_async_engine(admin_dsn, isolation_level="AUTOCOMMIT")
    try:
        async with engine.connect() as conn:
            await conn.exec_driver_sql(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
    finally:
        await engine.dispose()


async def _run_checks(
    *, admin_dsn: str, database: str, expected_version: str | None
) -> VerifyResult:
    result = VerifyResult(ok=True)
    dsn = make_url(admin_dsn).set(database=database).render_as_string(hide_password=False)
    engine = create_async_engine(dsn)
    try:
        async with engine.connect() as conn:
            found = {
                str(row[0])
                for row in (
                    await conn.execute(
                        text(
                            "SELECT table_name FROM information_schema.tables "
                            "WHERE table_schema = 'public'"
                        )
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
                version = (
                    await conn.execute(text("SELECT version_num FROM alembic_version"))
                ).scalar()
                if expected_version and str(version) != expected_version:
                    result.ok = False
                    result.problems.append(
                        f"Alembic-Version {version!r}, erwartet {expected_version!r}"
                    )
                else:
                    result.checks.append(f"Alembic-Version {version}")

            if "audit_events" in found:
                # Ein pgcrypto-Chiffrat fängt nicht mit einer lesbaren
                # JSON-Klammer an. Geprüft wird das Gegenteil des
                # ADR-Kriteriums — dass die Payloads verschlüsselt vorliegen.
                # Den Kundenschlüssel hat dieses Werkzeug nicht, und ein Dump
                # mit Klartext-Payloads wäre ein Fehler, den man sofort sehen
                # will.
                row = (
                    await conn.execute(
                        text(
                            "SELECT count(*), count(*) FILTER "
                            "(WHERE left(payload::text, 3) = '\\x7b') FROM audit_events"
                        )
                    )
                ).one_or_none()
                if row is not None:
                    total, plaintext = int(row[0]), int(row[1] or 0)
                    if total == 0:
                        result.checks.append("audit_events lesbar (leer)")
                    elif plaintext:
                        result.ok = False
                        result.problems.append(
                            f"{plaintext} von {total} Audit-Payloads liegen im Klartext vor"
                        )
                    else:
                        result.checks.append(f"{total} Audit-Payloads verschlüsselt")
    except Exception as exc:  # eine kaputte Datenbank ist ein Prüfergebnis
        result.ok = False
        result.problems.append(f"Prüfung abgebrochen: {type(exc).__name__}: {exc}")
    finally:
        await engine.dispose()
    return result


def _preflight(dump: Path, identity: Path) -> None:
    """Werkzeuge und Dateien prüfen, bevor eine Datenbank angelegt wird."""
    for tool in ("age", "pg_restore"):
        if shutil.which(tool) is None:
            raise BackupVerifyError(f"{tool} ist nicht installiert.")
    if not dump.is_file():
        raise BackupVerifyError(f"Dump {dump} fehlt.")
    if not identity.is_file():
        raise BackupVerifyError(
            f"Identitätsdatei {identity} fehlt. Dieses Werkzeug läuft dort, wo der "
            "private Backup-Schlüssel liegt."
        )


async def verify(
    *,
    admin_dsn: str,
    dump: Path,
    identity: Path,
    expected_checksum: str | None,
    expected_version: str | None,
    keep: bool,
) -> VerifyResult:
    # Im Thread: ein Dump liegt oft auf einem gemounteten Share, und ein
    # ``stat`` darauf kann hängen. Dieselbe Regel wie bei den LDAP-Aufrufen —
    # nichts Blockierendes im async Pfad.
    await asyncio.to_thread(_preflight, dump, identity)
    if expected_checksum:
        actual = await asyncio.to_thread(sha256_file, dump)
        if actual != expected_checksum.strip().lower():
            # Vor dem Entschlüsseln: eine veränderte Datei ist ein Vorfall und
            # kein Wiederherstellungsproblem.
            return VerifyResult(
                ok=False,
                problems=[
                    f"Die Prüfsumme von {dump.name} weicht ab. Der Dump wurde "
                    "verändert — nicht einspielen, Vorfall behandeln.\n"
                    f"  erwartet:    {expected_checksum.strip().lower()}\n"
                    f"  tatsächlich: {actual}"
                ],
            )

    database = "v_magister_" + datetime.now(UTC).strftime("%Y%m%d%H%M%S")
    if not DB_NAME.match(database):  # pragma: no cover - kann nicht auftreten
        raise BackupVerifyError(f"Datenbankname {database!r} ist nicht zulässig.")

    await _create_database(admin_dsn, database)
    try:
        try:
            await asyncio.to_thread(
                _decrypt_and_restore,
                dump=dump,
                identity=identity,
                database=database,
                admin_dsn=admin_dsn,
            )
        except BackupVerifyError as exc:
            return VerifyResult(ok=False, problems=[f"Einspielen gescheitert: {exc}"])
        return await _run_checks(
            admin_dsn=admin_dsn, database=database, expected_version=expected_version
        )
    finally:
        if keep:
            logger.warning("Prüf-Datenbank %s bleibt stehen (--keep)", database)
        else:
            await _drop_database(admin_dsn, database)


def add_parser(sub: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    """``backup``-Unterbefehle an ``magister-cli`` hängen."""
    bk = sub.add_parser(
        "backup",
        help="Sicherungen prüfen (ADR-0016 D9).",
        description=(
            "Prüf-Wiederherstellung einer Einzelinstallation. Braucht den "
            "PRIVATEN age-Schlüssel und läuft deshalb dort, wo er liegt — "
            "nicht auf dem Anwendungsserver."
        ),
    )
    bk_sub = bk.add_subparsers(dest="backup_action", required=True)
    vf = bk_sub.add_parser(
        "verify",
        help="Dump in eine Wegwerf-Datenbank einspielen und prüfen.",
        description=(
            "Ein Backup gilt erst als Backup, wenn es eingespielt wurde. "
            "Rückgabewert 1 heisst: diese Sicherung ist unbrauchbar."
        ),
    )
    vf.add_argument("--dump", required=True, type=Path, help="Die *.dump.age-Datei.")
    vf.add_argument(
        "--identity",
        required=True,
        type=Path,
        help="Private age-Identitätsdatei (age-keygen -o …).",
    )
    vf.add_argument(
        "--admin-dsn",
        default=None,
        help="Zugang mit CREATEDB. Vorgabe: MAGISTER_DATABASE_URL aus der Umgebung.",
    )
    vf.add_argument("--checksum", default=None, help="Erwartete SHA-256 der Datei.")
    vf.add_argument("--expected-schema-version", default=None)
    vf.add_argument("--keep", action="store_true", help="Prüf-Datenbank stehen lassen.")
    vf.set_defaults(func=cmd_verify)


def cmd_verify(args: argparse.Namespace) -> int:
    # Protokollierung hier und nicht nur in ``main``: über ``magister-cli``
    # wird diese Funktion direkt aufgerufen, und ohne Handler wäre ein
    # geglückter Lauf **stumm**. Für einen Cron-Job ist das der schlechteste
    # Zustand — kein Beweis, dass er gelaufen ist.
    if not logging.getLogger().handlers:
        logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    from magister_api.config import get_settings

    admin_dsn = args.admin_dsn or get_settings().database_url
    if not admin_dsn:
        logger.error("Kein DSN: --admin-dsn setzen oder MAGISTER_DATABASE_URL.")
        return 2
    try:
        result = asyncio.run(
            verify(
                admin_dsn=admin_dsn,
                dump=args.dump,
                identity=args.identity,
                expected_checksum=args.checksum,
                expected_version=args.expected_schema_version,
                keep=args.keep,
            )
        )
    except BackupVerifyError as exc:
        logger.error("%s", exc)
        return 2
    if result.ok:
        logger.info("Prüfung geglückt: %s", result.detail)
        return 0
    logger.error("Prüfung GESCHEITERT: %s", result.detail)
    return 1


__all__ = [
    "DB_NAME",
    "EXPECTED_TABLES",
    "BackupVerifyError",
    "VerifyResult",
    "add_parser",
    "cmd_verify",
    "libpq_env",
    "sha256_file",
    "verify",
]
