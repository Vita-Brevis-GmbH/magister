"""Prüf-Wiederherstellung auf dem Backup-Host (ADR-0016 D4).

    python -m cockpit_api.cli.verify_backup --dump … --identity … --slug …

Ein Backup gilt erst als Backup, wenn es eingespielt wurde. Dieses Werkzeug
spielt den jüngsten Dump in eine **Wegwerf-Datenbank** ein, prüft ihn und
verwirft sie wieder. Das Ergebnis geht an die Konsole; dort steht danach
„zuletzt geprüft".

Läuft **nicht** auf dem Anwendungsserver: es braucht den privaten
Backup-Schlüssel, und dass der dort nie liegt, ist die Zusage aus D2. Der Pfad
zur Identitätsdatei ist deshalb ein **Argument** und keine Einstellung — eine
Einstellung würde dazu verleiten, sie doch auf dem Anwendungsserver zu
konfigurieren.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
from pathlib import Path

from cockpit_api.cli._report import report
from cockpit_api.services.restore import verify_backup

logger = logging.getLogger("magister.verify-backup")


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="verify-backup",
        description="Prüf-Wiederherstellung eines Kunden-Dumps (ADR-0016 D4).",
    )
    p.add_argument("--admin-dsn", required=True, help="Verwaltungszugang in den Cluster.")
    p.add_argument("--dump", required=True, type=Path, help="Verschlüsselter Dump auf dem Share.")
    p.add_argument(
        "--identity",
        required=True,
        type=Path,
        help="Private age-Identitätsdatei. Liegt auf DIESEM Host, nie auf dem Anwendungsserver.",
    )
    p.add_argument("--slug", required=True)
    p.add_argument("--schema", required=True, help="Schemaname im Dump, z. B. t_musterstadt.")
    p.add_argument("--expected-schema-version", default=None)
    p.add_argument(
        "--checksum",
        default=None,
        help="Erwartete SHA-256 der verschlüsselten Datei. Weicht sie ab, wird "
        "NICHT eingespielt — eine veränderte Datei ist ein Vorfall.",
    )
    p.add_argument(
        "--rows",
        action="append",
        default=[],
        metavar="TABELLE=ANZAHL",
        help="Referenz-Zeilenzahl aus der Produktion, mehrfach möglich. Geprüft "
        "wird auf plausible Grössenordnung, nicht auf Gleichheit.",
    )
    p.add_argument(
        "--keep",
        action="store_true",
        help="Die Prüf-Datenbank stehen lassen. Nur zur Fehlersuche.",
    )
    p.add_argument("--console", default=None, help="Basis-URL des Management-Listeners.")
    p.add_argument("--backup-id", default=None, help="Id der Sicherung in der Konsole.")
    p.add_argument("--ca-bundle", default=None)
    return p


def _row_counts(values: list[str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in values:
        table, _, number = item.partition("=")
        if not number.isdigit():
            raise SystemExit(f"--rows erwartet TABELLE=ANZAHL, nicht {item!r}")
        counts[table.strip()] = int(number)
    return counts


async def _run(args: argparse.Namespace) -> int:
    result = await verify_backup(
        admin_dsn=args.admin_dsn,
        dump_path=args.dump,
        identity_file=args.identity,
        slug=args.slug,
        schema_name=args.schema,
        expected_schema_version=args.expected_schema_version,
        expected_checksum=args.checksum,
        reference_row_counts=_row_counts(args.rows) or None,
        keep=args.keep,
    )
    if result.ok:
        logger.info("Prüfung geglückt: %s", result.detail)
    else:
        logger.error("Prüfung GESCHEITERT: %s", result.detail)

    if args.console and args.backup_id:
        token = os.environ.get("COCKPIT_BOOTSTRAP_TOKEN", "")
        marker = os.environ.get("COCKPIT_MANAGEMENT_MARKER", "")
        if not token or not marker:
            logger.warning(
                "COCKPIT_BOOTSTRAP_TOKEN oder COCKPIT_MANAGEMENT_MARKER fehlt — "
                "das Ergebnis wird nicht gemeldet. Die Prüfung selbst ist gelaufen."
            )
        else:
            report(
                console=args.console,
                path=f"/api/backups/{args.backup_id}/verify-result",
                ok=result.ok,
                detail=result.detail,
                token=token,
                marker=marker,
                ca_bundle=args.ca_bundle,
            )
    elif args.console or args.backup_id:
        logger.warning("--console und --backup-id gehören zusammen; nichts gemeldet.")

    # Rückgabewert für den Cron-Job: 1 heisst „diese Sicherung ist unbrauchbar".
    return 0 if result.ok else 1


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    args = _parser().parse_args(argv)
    return asyncio.run(_run(args))


if __name__ == "__main__":
    sys.exit(main())
