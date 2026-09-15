"""Warum ein TOTP-Code nicht passt — Uhr oder Geheimnis (ADR-0020 D2).

Zwei Ursachen sehen für den Anwender gleich aus („Der Code stimmt nicht"),
brauchen aber verschiedene Handgriffe:

* **Die Uhr des Servers geht falsch.** Ein Code gilt dreissig Sekunden; das
  Fenster der Anmeldung deckt eine Abweichung von einem Schritt ab. Geht die
  Serveruhr weiter daneben, passt kein Code — mit jeder App, auf jedem
  Telefon. Abhilfe: Zeitsynchronisation auf dem Host.
* **Das Geheimnis passt nicht zu dem, was die App gespeichert hat.** Etwa,
  weil zwischendurch ein zweites Mal „einrichten" geklickt wurde: das
  überschreibt das Geheimnis, der alte QR-Code gilt dann nicht mehr.

Dieses Werkzeug prüft den vorgelegten Code gegen ein **weites** Fenster
(±5 Minuten) und sagt, welcher Fall vorliegt:

    python -m cockpit_api.cli.totp_probe --upn person@example.ch --code 123456

Es zeigt **keinen** gültigen Code an und schreibt keinen in ein Protokoll:
es sagt nur, zu welchem Zeitschritt der eingegebene gehört hätte.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import UTC, datetime

import pyotp
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from cockpit_api import totp
from cockpit_api.config import settings
from cockpit_api.models.operator import ConsoleOperator

#: Wie weit um „jetzt" herum gesucht wird. Fünf Minuten sind genug, um eine
#: schiefe Uhr zu erkennen, und wenig genug, dass „passt nirgends" wirklich
#: heisst: das Geheimnis ist ein anderes.
SUCHFENSTER_SCHRITTE = 10


def _parse(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Einen TOTP-Code einordnen.")
    p.add_argument("--upn", required=True, help="Der Operator, um den es geht.")
    p.add_argument("--code", required=True, help="Der Code, den die App gerade zeigt.")
    return p.parse_args(argv)


async def _run(args: argparse.Namespace) -> int:
    engine = create_async_engine(settings.database_url)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with maker() as session:
            operator = (
                await session.execute(
                    select(ConsoleOperator).where(
                        func.lower(ConsoleOperator.upn) == args.upn.strip().lower()
                    )
                )
            ).scalar_one_or_none()
            if operator is None:
                print(f"Kein Operator mit {args.upn}.", file=sys.stderr)
                return 1
            if not settings.secret_key:
                print("COCKPIT_SECRET_KEY ist nicht gesetzt.", file=sys.stderr)
                return 2
            geheimnis = (
                await session.execute(
                    select(
                        func.pgp_sym_decrypt(ConsoleOperator.totp_secret_enc, settings.secret_key)
                    ).where(ConsoleOperator.id == operator.id)
                )
            ).scalar_one_or_none()

        jetzt = datetime.now(UTC)
        print(f"Serverzeit (UTC):   {jetzt.isoformat(timespec='seconds')}")
        print(f"Zeitschritt:        {totp.current_step()}")
        print("Zweiter Faktor:     ", end="")
        if not geheimnis:
            print("kein Geheimnis hinterlegt — die Einrichtung ist nie angekommen.")
            return 3
        print("bestätigt" if operator.totp_confirmed_at else "eingerichtet, unbestätigt")
        print(f"Letzter Schritt:    {operator.totp_last_step or '—'}")

        code = args.code.strip().replace(" ", "")
        rechner = pyotp.TOTP(geheimnis, digits=totp.DIGITS, interval=totp.PERIOD)
        jetzt_schritt = totp.current_step()
        for versatz in range(-SUCHFENSTER_SCHRITTE, SUCHFENSTER_SCHRITTE + 1):
            if rechner.at((jetzt_schritt + versatz) * totp.PERIOD) != code:
                continue
            sekunden = versatz * totp.PERIOD
            if abs(versatz) <= 1:
                print(f"\nDer Code passt (Versatz {sekunden:+d} s) — die Uhr ist in Ordnung.")
                print("Wenn die Anmeldung ihn trotzdem abweist, war er schon verbraucht:")
                print("ein Code gilt einmal. Den nächsten abwarten.")
                return 0
            print(f"\nDer Code passt, aber mit {sekunden:+d} Sekunden Versatz.")
            print("Das ist mehr, als die Anmeldung durchlässt (±30 s).")
            print("Die Uhr des Servers oder des Telefons geht falsch — auf dem Host:")
            print("    timedatectl set-ntp true && timedatectl")
            return 4

        print("\nDer Code passt zu KEINEM Zeitschritt in ±5 Minuten.")
        print("Dann ist es nicht die Uhr, sondern das Geheimnis: die App hält ein")
        print("anderes als die Datenbank. Das passiert, wenn 'einrichten' ein")
        print("zweites Mal geklickt wurde — der ältere QR-Code gilt dann nicht mehr.")
        print("Abhilfe: den zweiten Faktor zurücksetzen und neu einrichten.")
        return 5
    finally:
        await engine.dispose()


def main(argv: list[str] | None = None) -> int:
    return asyncio.run(_run(_parse(argv)))


if __name__ == "__main__":
    raise SystemExit(main())
