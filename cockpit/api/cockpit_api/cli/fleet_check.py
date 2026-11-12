"""``python -m cockpit_api.cli.fleet_check`` — Flotte prüfen (ADR-0021 D6).

Der Alarm über die Connector-Flotte kommt aus einem **Exit-Code** und nicht
aus Magister: kein SMTP, keine Webhooks, keine Alarmierungs-Konfiguration.
Eine zweite Alarmierung neben der, die es im Betrieb schon gibt, ist eine, die
niemand pflegt — und die dann genau in der Nacht schweigt, in der sie zählt.

Aufruf aus der Überwachung (Icinga, Zabbix, was auch immer schon läuft):

    python -m cockpit_api.cli.fleet_check

Exit-Codes nach der üblichen Konvention: ``0`` in Ordnung, ``1`` Warnung,
``2`` kritisch. Mit ``--quiet`` schreibt es nur die Zusammenfassung, mit
``--json`` maschinenlesbar.

Läuft auf dem **Konsolen-Host** und liest die Konsolen-Datenbank direkt. Nicht
über die HTTP-Fläche: dann bräuchte die Überwachung einen Token, und ein
Token in einer Cron-Zeile ist ein Token, das dort auch noch in zwei Jahren
steht.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from dataclasses import asdict

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from cockpit_api.config import settings
from cockpit_api.services.fleet import Finding, Severity, exit_code, fleet_findings

#: Wie die Zeilen anfangen. Kurz, damit die Meldung in eine Benachrichtigung
#: passt, die ein Mensch auf dem Telefon liest.
MARK = {Severity.critical: "KRITISCH", Severity.warning: "WARNUNG "}


def _parse(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Befunde über die Connector-Flotte. Exit 0/1/2.",
    )
    parser.add_argument("--json", action="store_true", help="maschinenlesbar ausgeben")
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="nur die Zusammenfassung, keine Einzelbefunde",
    )
    return parser.parse_args(argv)


async def _collect() -> list[Finding]:
    engine = create_async_engine(settings.database_url)
    try:
        sm = async_sessionmaker(engine, expire_on_commit=False)
        async with sm() as session:
            return await fleet_findings(session)
    finally:
        await engine.dispose()


def _report(findings: list[Finding], *, as_json: bool, quiet: bool) -> None:
    if as_json:
        sys.stdout.write(
            json.dumps(
                {"findings": [asdict(f) for f in findings], "worst": exit_code(findings)},
                ensure_ascii=False,
                indent=2,
            )
            + "\n"
        )
        return
    critical = sum(1 for f in findings if f.severity is Severity.critical)
    warnings = len(findings) - critical
    if not findings:
        sys.stdout.write("Flotte in Ordnung: keine Befunde.\n")
        return
    # Die Zusammenfassung ZUERST: ein Überwachungssystem schneidet die Ausgabe
    # oft nach der ersten Zeile ab, und die soll dann die Antwort tragen.
    sys.stdout.write(f"{critical} kritisch, {warnings} Warnung(en).\n")
    if quiet:
        return
    for f in findings:
        where = f"{f.tenant_slug}/{f.agent_name}" if f.agent_name else f.tenant_slug
        sys.stdout.write(f"{MARK[f.severity]} {where}: {f.detail}\n")


def main(argv: list[str] | None = None) -> int:
    args = _parse(argv)
    findings = asyncio.run(_collect())
    _report(findings, as_json=args.json, quiet=args.quiet)
    return exit_code(findings)


if __name__ == "__main__":
    raise SystemExit(main())
