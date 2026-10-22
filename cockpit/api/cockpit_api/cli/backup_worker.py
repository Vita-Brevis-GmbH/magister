"""Prüfer auf dem Backup-Host: prüft Sicherungen, spielt Wiederherstellungen ein (ADR-0024 D6).

    python -m cockpit_api.cli.backup_worker --identity /pfad/backup-age.key

Ein Lauf holt sich bei der Konsole, was zu tun ist (``/api/backups/worker-queue``),
erledigt es und meldet die Ergebnisse über die bestehenden Endpunkte. Gedacht
für einen systemd-Timer alle paar Minuten (``plattform-aufbau.sh
backup-pruefer`` richtet ihn ein).

Vorher gab es die Werkzeuge ``verify_backup`` und ``restore_backup`` nur als
Einzelaufrufe mit Pfad, Schema und Id auf der Kommandozeile — in der Konsole
stand deshalb jede Sicherung auf „geschrieben", bis jemand das von Hand tat,
und eine erfasste Wiederherstellung blieb liegen.

**Wo das läuft, ist der Punkt** (ADR-0016 D2): hier liegt der private
Backup-Schlüssel, und er liegt nicht im Container der Konsole. Auf einem
Einzelhost (Test, dev01) startet der Timer dafür einen eigenen, kurzlebigen
Container aus demselben Abbild, in den nur der Schlüssel eingehängt wird.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import socket
import sys
from pathlib import Path
from typing import Any

import httpx

from cockpit_api.cli._report import report
from cockpit_api.services.restore import RestoreError, restore_dump, verify_backup

logger = logging.getLogger("magister.backup-worker")


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="backup-worker", description=__doc__)
    p.add_argument(
        "--console",
        default=os.environ.get("COCKPIT_WORKER_CONSOLE", "http://api:8000"),
        help="Basis-URL der Konsole (Vorgabe: der Dienst im selben Compose-Netz).",
    )
    p.add_argument(
        "--identity",
        type=Path,
        required=True,
        help="Private age-Identität. Liegt auf DIESEM Host, nie im Konsolen-Container.",
    )
    p.add_argument(
        "--admin-dsn",
        default=os.environ.get("COCKPIT_TENANT_ADMIN_DSN", ""),
        help="Verwaltungszugang in den Cluster für die Wegwerf-Datenbanken.",
    )
    p.add_argument("--ca-bundle", default=None)
    return p


def _headers() -> dict[str, str]:
    token = os.environ.get("COCKPIT_WORKER_TOKEN") or os.environ.get("COCKPIT_BOOTSTRAP_TOKEN", "")
    marker = os.environ.get("COCKPIT_MANAGEMENT_MARKER", "")
    if not token or not marker:
        raise SystemExit(
            "COCKPIT_WORKER_TOKEN (oder COCKPIT_BOOTSTRAP_TOKEN) und "
            "COCKPIT_MANAGEMENT_MARKER müssen gesetzt sein."
        )
    return {"Authorization": f"Bearer {token}", "X-Magister-Management": marker}


def _queue(console: str, headers: dict[str, str], ca_bundle: str | None) -> dict[str, Any]:
    url = f"{console.rstrip('/')}/api/backups/worker-queue"
    detail = f"host={socket.gethostname()}"
    with httpx.Client(timeout=30.0, verify=ca_bundle or True) as client:
        resp = client.get(url, headers=headers, params={"detail": detail})
    resp.raise_for_status()
    body: dict[str, Any] = resp.json()
    return body


async def _run(args: argparse.Namespace) -> int:
    if not args.admin_dsn:
        raise SystemExit("--admin-dsn bzw. COCKPIT_TENANT_ADMIN_DSN fehlt.")
    headers = _headers()
    try:
        queue = _queue(args.console, headers, args.ca_bundle)
    except httpx.HTTPError as exc:
        logger.error("Konsole nicht erreichbar oder Abruf abgewiesen: %s", exc)
        return 2
    token = headers["Authorization"].removeprefix("Bearer ")
    marker = headers["X-Magister-Management"]
    failures = 0

    for item in queue.get("verify", []):
        logger.info("Prüfe Sicherung %s (%s)", item["backup_id"], item["tenant_slug"])
        result = await verify_backup(
            admin_dsn=args.admin_dsn,
            dump_path=Path(item["path"]),
            identity_file=args.identity,
            slug=item["tenant_slug"],
            schema_name=item["schema_name"],
            expected_schema_version=item.get("schema_version"),
            expected_checksum=item.get("checksum_sha256"),
        )
        failures += 0 if result.ok else 1
        report(
            console=args.console,
            path=f"/api/backups/{item['backup_id']}/verify-result",
            ok=result.ok,
            detail=result.detail,
            token=token,
            marker=marker,
            ca_bundle=args.ca_bundle,
        )

    for item in queue.get("restore", []):
        logger.info("Spiele Wiederherstellung %s ein (%s)", item["job_id"], item["tenant_slug"])
        ok, detail = True, f"in Datenbank {item['target_database']} eingespielt"
        try:
            await restore_dump(
                admin_dsn=args.admin_dsn,
                dump_path=Path(item["path"]),
                identity_file=args.identity,
                target_database=item["target_database"],
                expected_checksum=item.get("checksum_sha256"),
            )
        except RestoreError as exc:
            ok, detail = False, str(exc)
            failures += 1
        report(
            console=args.console,
            path=f"/api/restore-jobs/{item['job_id']}/report",
            ok=ok,
            detail=detail,
            token=token,
            marker=marker,
            ca_bundle=args.ca_bundle,
        )

    done = len(queue.get("verify", [])) + len(queue.get("restore", []))
    logger.info("Lauf beendet: %d Auftrag/Aufträge, %d gescheitert", done, failures)
    return 1 if failures else 0


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    return asyncio.run(_run(_parser().parse_args(argv)))


if __name__ == "__main__":
    sys.exit(main())
