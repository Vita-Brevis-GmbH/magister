"""``magister-cli local-admin totp-reset`` — the reset actions on the server.

An On-prem installation has no console (ADR-0013 D8 makes it the same platform
with one tenant, but the Global-Admin surface lives at Vita Brevis). The four
interventions of ADR-0015 D2 therefore also need a path that works with nothing
but a shell on the box.

This grants no new rights: whoever has a shell here has database access anyway.
What it adds is that the intervention is *audited* instead of being a hand-typed
``UPDATE`` nobody can reconstruct afterwards.
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from magister_api.audit.service import AuditService
from magister_api.config import get_settings
from magister_api.services.local_admin_mfa import LocalAdminMfaService

#: Actor recorded in the audit trail. There is no authenticated user on this
#: path, and pretending otherwise would be worse than naming the channel.
CLI_ACTOR = "cli@localhost"


async def _run(*, new_recovery_codes: bool, disable: bool, reason: str) -> int:
    settings = get_settings()
    engine = create_async_engine(settings.database_url)
    sm = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with sm() as session:
            mfa = LocalAdminMfaService(session, settings)
            audit = AuditService(session, settings)

            if disable:
                from magister_api.services.local_admin import LocalAdminService

                admin = await LocalAdminService(session).set_enabled(False)
                if admin is None:
                    sys.stderr.write("Kein lokales Konto vorhanden.\n")
                    return 1
                await audit.emit(
                    action="local_account_disabled",
                    target_kind="local_admin",
                    target_id="1",
                    actor_upn=CLI_ACTOR,
                    actor_object_guid=None,
                    school_id=None,
                    ip=None,
                    request_id="cli",
                    payload={"via": "cli", "reason": reason},
                )
                await session.commit()
                print(f'Konto "{admin.username}" deaktiviert. Der Notzugang ist zu.')
                return 0

            if new_recovery_codes:
                codes = await mfa.regenerate_recovery_codes()
                if codes is None:
                    sys.stderr.write(
                        "Kein zweiter Faktor eingerichtet — es gibt nichts zu erneuern.\n"
                        "Ohne --new-recovery-codes aufrufen, um den Faktor zurückzusetzen.\n"
                    )
                    return 1
                await audit.emit(
                    action="local_recovery_codes_regenerated",
                    target_kind="local_admin",
                    target_id="1",
                    actor_upn=CLI_ACTOR,
                    actor_object_guid=None,
                    school_id=None,
                    ip=None,
                    request_id="cli",
                    payload={"via": "cli", "count": len(codes), "reason": reason},
                )
                await session.commit()
                print("Neue Wiederherstellungscodes — sie werden nur jetzt angezeigt:\n")
                for code in codes:
                    print(f"  {code}")
                return 0

            if not await mfa.reset(actor=CLI_ACTOR):
                sys.stderr.write("Kein lokales Konto vorhanden.\n")
                return 1
            await audit.emit(
                action="local_totp_reset",
                target_kind="local_admin",
                target_id="1",
                actor_upn=CLI_ACTOR,
                actor_object_guid=None,
                school_id=None,
                ip=None,
                request_id="cli",
                payload={"via": "cli", "forces_enrollment": True, "reason": reason},
            )
            await session.commit()
            print(
                "Zweiter Faktor zurückgesetzt. Einrichtung beim nächsten Anmelden "
                "erforderlich; die MFA-Pflicht bleibt bestehen."
            )
            return 0
    finally:
        await engine.dispose()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="magister-cli local-admin totp-reset",
        description=(
            "Zweiten Faktor des lokalen Notkontos zurücksetzen. Ohne Optionen wird der "
            "Faktor gelöscht und beim nächsten Anmelden neu eingerichtet."
        ),
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--new-recovery-codes",
        action="store_true",
        help="Nur neue Wiederherstellungscodes erzeugen; das Geheimnis bleibt unberührt.",
    )
    group.add_argument(
        "--disable",
        action="store_true",
        help="Das Konto deaktivieren. Der Notzugang ist damit zu, ohne dass etwas geschwächt wird.",
    )
    parser.add_argument(
        "--reason",
        default="",
        help="Grund oder Ticketnummer für das Audit (empfohlen).",
    )
    args = parser.parse_args(argv)
    return asyncio.run(
        _run(
            new_recovery_codes=args.new_recovery_codes,
            disable=args.disable,
            reason=args.reason[:200],
        )
    )


if __name__ == "__main__":
    raise SystemExit(main())
