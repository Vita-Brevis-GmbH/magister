"""Einen Operator für die Konsole eintragen (ADR-0020 D5).

Drei Teile hat der Handgriff, und zwei davon macht dieses Werkzeug nicht:

1. **Zertifikat ausstellen** — aus der Plattform-CA, siehe
   `docs/runbooks/platform-ca.md`. Nicht hier: dafür gibt es eine Zeremonie.
2. **Fingerprint bilden und Zeile anlegen** — das ist dieser Befehl.
3. **Zweiten Faktor einrichten** — macht die Person selbst beim ersten
   Anmelden. Ein Betreiber, der einen fremden zweiten Faktor einrichten kann,
   ist kein zweiter Faktor.

Ein Befehl und **keine** Oberfläche: bei zwei Personen wäre eine
Benutzerverwaltung mehr Fläche als Nutzen — und sie wäre die Fläche, über die
man sich selbst Rechte gibt.

    python -m cockpit_api.cli.add_operator \\
        --upn matthias.hadorn@vitabrevis.ch \\
        --name "Matthias Hadorn" \\
        --cert /pfad/zu/operator-matthias.pem

Widerruf braucht nur den UPN — wer abgeschaltet wird, hat das Zertifikat
unter Umständen gerade verloren:

    python -m cockpit_api.cli.add_operator --upn … --disable
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from cockpit_api.config import settings
from cockpit_api.models.operator import ConsoleOperator
from cockpit_api.services.connector_ca import spki_fingerprint_from_certificate


def _parse(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Operator der Konsole eintragen.")
    parser.add_argument("--upn", required=True, help="Was im Protokoll steht.")
    parser.add_argument("--name", default=None, help="Anzeigename. Beim Anlegen Pflicht.")
    parser.add_argument(
        "--cert",
        default=None,
        type=Path,
        help="Das Client-Zertifikat der Person (PEM). Nur der öffentliche Teil.",
    )
    parser.add_argument(
        "--disable",
        action="store_true",
        help="Den Operator abschalten statt anlegen — der Widerruf pro Person.",
    )
    args = parser.parse_args(argv)
    # Zum Abschalten braucht es weder Zertifikat noch Namen: wer widerrufen
    # wird, hat unter Umständen genau das verloren, was hier sonst verlangt
    # würde. Beim Anlegen sind beide Pflicht.
    if not args.disable and (args.cert is None or args.name is None):
        parser.error("--cert und --name sind zum Anlegen nötig (ohne --disable).")
    return args


async def _run(args: argparse.Namespace) -> int:
    fingerprint = ""
    if args.cert is not None:
        if not args.cert.is_file():
            print(f"Zertifikat {args.cert} fehlt.", file=sys.stderr)
            return 2
        try:
            fingerprint = spki_fingerprint_from_certificate(args.cert.read_bytes())
        except Exception as exc:
            # Die Meldung des Dienstes benennt die Ursache schon; ein zweites
            # „Zertifikat ist nicht lesbar“ davor wäre nur Lärm.
            print(str(exc), file=sys.stderr)
            return 2

    engine = create_async_engine(settings.database_url)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with maker() as session:
            existing = (
                await session.execute(
                    select(ConsoleOperator).where(ConsoleOperator.upn == args.upn)
                )
            ).scalar_one_or_none()

            if args.disable:
                if existing is None:
                    print(f"Kein Operator mit {args.upn}.", file=sys.stderr)
                    return 1
                existing.enabled = False
                await session.commit()
                print(f"{args.upn} abgeschaltet. Das Zertifikat gehört zusätzlich gesperrt.")
                return 0

            clash = (
                await session.execute(
                    select(ConsoleOperator).where(
                        ConsoleOperator.spki_fingerprint == fingerprint,
                        ConsoleOperator.upn != args.upn,
                    )
                )
            ).scalar_one_or_none()
            if clash is not None:
                # Ein Schlüsselpaar gehört einer Person. Zwei Zeilen darauf
                # hiessen: zwei Namen für dieselbe Anmeldung.
                print(
                    f"Dieses Zertifikat gehört schon {clash.upn}. Ein Schlüsselpaar, eine Person.",
                    file=sys.stderr,
                )
                return 1

            if existing is not None:
                # Ein neues Zertifikat für dieselbe Person: der Fingerprint
                # wird ersetzt, der zweite Faktor bleibt. Wer das Telefon
                # behält, richtet es nicht neu ein.
                existing.name = args.name
                existing.spki_fingerprint = fingerprint
                existing.enabled = True
                await session.commit()
                print(f"{args.upn}: Zertifikat ersetzt ({fingerprint[:16]}…).")
                return 0

            session.add(ConsoleOperator(upn=args.upn, name=args.name, spki_fingerprint=fingerprint))
            await session.commit()
            print(
                f"{args.upn} eingetragen ({fingerprint[:16]}…). "
                "Der zweite Faktor wird beim ersten Anmelden eingerichtet."
            )
            return 0
    finally:
        await engine.dispose()


def main(argv: list[str] | None = None) -> int:
    return asyncio.run(_run(_parse(argv)))


if __name__ == "__main__":
    raise SystemExit(main())
