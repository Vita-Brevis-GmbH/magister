"""Einen Operator für die Konsole eintragen (ADR-0020 D5, ADR-0023 D5).

Der Handgriff hat drei Teile, und einen davon macht dieses Werkzeug nicht:

1. **Zeile anlegen und ersten Faktor setzen** — das ist dieser Befehl. Seit
   ADR-0023 D1 ist der erste Faktor in der Regel ein Passwort
   (`--set-password`); ein Client-Zertifikat (`--cert`) geht weiterhin, und
   beides nebeneinander ebenfalls.
2. **Zweiten Faktor einrichten** — macht die Person selbst beim ersten
   Anmelden. Ein Betreiber, der einen fremden zweiten Faktor einrichten kann,
   ist kein zweiter Faktor.
3. **Zertifikat ausstellen**, wo eines benutzt wird — aus der Plattform-CA,
   siehe `docs/runbooks/platform-ca.md`. Nicht hier: dafür gibt es eine
   Zeremonie.

Ein Befehl und **keine** Oberfläche: bei zwei Personen wäre eine
Benutzerverwaltung mehr Fläche als Nutzen — und sie wäre die Fläche, über die
man sich selbst Rechte gibt.

    python -m cockpit_api.cli.add_operator \\
        --upn matthias.hadorn@vitabrevis.ch \\
        --name "Matthias Hadorn" \\
        --set-password

Das Passwort wird **abgefragt**, nicht als Argument übergeben: was in der
Kommandozeile steht, steht in der Prozessliste und in der Shell-Historie.

Widerruf braucht nur den UPN — wer abgeschaltet wird, hat das Zertifikat
unter Umständen gerade verloren:

    python -m cockpit_api.cli.add_operator --upn … --disable
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import sys
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from cockpit_api import passwords
from cockpit_api.config import settings
from cockpit_api.models.operator import ConsoleOperator
from cockpit_api.services.connector_ca import spki_fingerprint_from_certificate
from cockpit_api.services.console_auth import ConsoleAuthService


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
        "--set-password",
        action="store_true",
        help="Passwort setzen oder ersetzen. Wird abgefragt, nie als Argument übergeben.",
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
    if args.disable:
        return args
    if args.name is None:
        parser.error("--name ist zum Anlegen nötig.")
    if args.cert is None and not args.set_password:
        # Ein Operator ohne beides könnte sich nicht anmelden. Das ist ein
        # gültiger Zustand (ADR-0023 D5) — aber keiner, den man versehentlich
        # anlegt, deshalb muss er ausdrücklich gewollt sein.
        parser.error(
            "Ohne --set-password und ohne --cert hätte dieser Operator keinen ersten "
            "Faktor und könnte sich nie anmelden. Eines von beiden angeben."
        )
    return args


def _passwort_abfragen() -> str | None:
    """Zweimal eingeben, nie anzeigen, nie in der Kommandozeile.

    `getpass` liest ohne Echo. Zweimal, weil ein Tippfehler sonst erst beim
    Anmelden auffällt — und dann von jemandem, der nicht mehr weiss, was er
    getippt hat.
    """
    erste = getpass.getpass("Passwort: ")
    if len(erste) < passwords.MIN_LENGTH:
        print(
            f"Zu kurz: mindestens {passwords.MIN_LENGTH} Zeichen (ADR-0023 D1).",
            file=sys.stderr,
        )
        return None
    if erste != getpass.getpass("Passwort wiederholen: "):
        print("Die beiden Eingaben sind verschieden.", file=sys.stderr)
        return None
    return erste


async def _run(args: argparse.Namespace) -> int:
    fingerprint: str | None = None
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

    passwort: str | None = None
    if getattr(args, "set_password", False):
        passwort = _passwort_abfragen()
        if passwort is None:
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

            clash = None
            if fingerprint:
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
                # Ein neues Zertifikat oder ein neues Passwort für dieselbe
                # Person: der erste Faktor wird ersetzt, der zweite bleibt.
                # Wer das Telefon behält, richtet es nicht neu ein.
                existing.name = args.name
                if fingerprint:
                    existing.spki_fingerprint = fingerprint
                if passwort is not None:
                    await ConsoleAuthService(session).set_password(existing, passwort)
                existing.enabled = True
                await session.commit()
                print(f"{args.upn}: {_was_gesetzt(fingerprint, passwort)} ersetzt.")
                return 0

            operator = ConsoleOperator(
                upn=args.upn, name=args.name, spki_fingerprint=fingerprint or None
            )
            session.add(operator)
            await session.flush()
            if passwort is not None:
                await ConsoleAuthService(session).set_password(operator, passwort)
            await session.commit()
            print(
                f"{args.upn} eingetragen ({_was_gesetzt(fingerprint, passwort)}). "
                "Der zweite Faktor wird beim ersten Anmelden eingerichtet."
            )
            return 0
    finally:
        await engine.dispose()


def _was_gesetzt(fingerprint: str | None, passwort: str | None) -> str:
    teile: list[str] = []
    if fingerprint:
        teile.append(f"Zertifikat {fingerprint[:16]}…")
    if passwort is not None:
        teile.append("Passwort")
    return " und ".join(teile) or "nichts"


def main(argv: list[str] | None = None) -> int:
    return asyncio.run(_run(_parse(argv)))


if __name__ == "__main__":
    raise SystemExit(main())
