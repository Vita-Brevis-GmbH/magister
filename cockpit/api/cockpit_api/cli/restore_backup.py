"""Wiederherstellung auf dem Backup-Host (ADR-0016 D5).

    python -m cockpit_api.cli.restore_backup --dump … --target-database r_…

Eingespielt wird in eine **eigene Datenbank**. Das Produktivschema wird nicht
einmal geöffnet — es liegt in einer anderen Datenbank. Umschalten ist ein
getrennter Schritt mit zweiter Person und steht in
``docs/runbooks/sicherung-wiederherstellung.md``.

Läuft **nicht** auf dem Anwendungsserver: es braucht den privaten
Backup-Schlüssel (ADR-0016 D2).
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
from pathlib import Path

from cockpit_api.cli._report import report
from cockpit_api.services.restore import RestoreError, restore_dump

logger = logging.getLogger("magister.restore-backup")


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="restore-backup",
        description="Kunden-Dump in eine eigene Datenbank einspielen (ADR-0016 D5).",
    )
    p.add_argument("--admin-dsn", required=True)
    p.add_argument("--dump", required=True, type=Path)
    p.add_argument("--identity", required=True, type=Path)
    p.add_argument(
        "--target-database",
        required=True,
        help="Neue Datenbank, z. B. r_musterstadt_20260909104500. Muss noch nicht existieren.",
    )
    p.add_argument(
        "--checksum",
        default=None,
        help="Erwartete SHA-256 der verschlüsselten Datei. Weicht sie ab, wird NICHT eingespielt.",
    )
    p.add_argument("--console", default=None)
    p.add_argument("--job-id", default=None, help="Id des Wiederherstellungsauftrags.")
    p.add_argument("--ca-bundle", default=None)
    return p


async def _run(args: argparse.Namespace) -> int:
    detail = ""
    ok = True
    try:
        await restore_dump(
            admin_dsn=args.admin_dsn,
            dump_path=args.dump,
            identity_file=args.identity,
            target_database=args.target_database,
            expected_checksum=args.checksum,
        )
        detail = f"in Datenbank {args.target_database} eingespielt"
        logger.info("%s", detail)
    except RestoreError as exc:
        ok = False
        detail = str(exc)
        logger.error("Wiederherstellung gescheitert: %s", detail)

    if args.console and args.job_id:
        token = os.environ.get("COCKPIT_BOOTSTRAP_TOKEN", "")
        marker = os.environ.get("COCKPIT_MANAGEMENT_MARKER", "")
        if not token or not marker:
            logger.warning(
                "COCKPIT_BOOTSTRAP_TOKEN oder COCKPIT_MANAGEMENT_MARKER fehlt — "
                "das Ergebnis wird nicht gemeldet."
            )
        else:
            report(
                console=args.console,
                path=f"/api/restore-jobs/{args.job_id}/report",
                ok=ok,
                detail=detail,
                token=token,
                marker=marker,
                ca_bundle=args.ca_bundle,
            )
    elif args.console or args.job_id:
        logger.warning("--console und --job-id gehören zusammen; nichts gemeldet.")
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    args = _parser().parse_args(argv)
    return asyncio.run(_run(args))


if __name__ == "__main__":
    sys.exit(main())
