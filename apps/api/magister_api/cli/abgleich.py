"""Abgleich mit der Konsole einmal von Hand, mit Befund je Kunde (ADR-0017 D3, ADR-0024).

Aufruf im Container der Datenebene::

    python -m magister_api.cli.abgleich             # abgleichen und berichten
    python -m magister_api.cli.abgleich --nur-zeigen  # nur berichten, nichts schreiben
    python -m magister_api.cli.abgleich --kunde acme

Wozu: „In der Konsole steht Firma, im Portal Schule" hat zwei Abende gekostet,
weil zwischen den beiden nichts zu sehen war. Dieses Werkzeug zeigt für jeden
Kunden die Kette in einer Zeile pro Glied — kennt die Datenebene ihn als
Konsolen-Kunden, was will die Konsole, was steht im Kundenschema, was fehlt —
und führt danach genau den Abgleich aus, den auch die Schleife ausführt.

Gibt nur Namen, Profile und Feldnamen aus, nie Werte von Einstellungen und
nie Geheimnisse. Fehlermeldungen nur mit ihrer ersten Zeile: SQLAlchemy hängt
die gebundenen Parameter in weiteren Zeilen an.
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from magister_api.config import Settings, get_settings
from magister_api.services.app_settings import AppSettingsService
from magister_api.services.reconcile_loop import reconcile_tenant, tenant_keys
from magister_api.services.reconciler import Reconciler
from magister_api.tenancy.context import (
    dispose_tenancy,
    get_engines,
    get_registry,
    init_tenancy,
    refresh_from_console,
)
from magister_api.tenancy.desired_state import (
    DesiredStateUnavailableError,
    fetch_desired_state,
)
from magister_api.tenancy.keys import attach_keys
from magister_api.tenancy.registry import Tenant
from magister_api.tenancy.scope import apply_tenant_scope


def _out(msg: str) -> None:
    # Ein CLI schreibt auf stdout, nicht in den Logger — die Logger-Regel gilt
    # für den Backend-Code im Request-Pfad.
    sys.stdout.write(msg + "\n")
    sys.stdout.flush()


def _first_line(exc: BaseException) -> str:
    text = str(exc).strip().splitlines()
    return f"{type(exc).__name__}: {text[0][:300] if text else ''}"


async def _current(settings: Settings, tenant: Tenant) -> tuple[str, dict[str, bool], int]:
    async with get_engines().sessionmaker_for(tenant)() as session:
        attach_keys(session, tenant_keys(settings, tenant))
        await apply_tenant_scope(session, tenant, extension_schema=settings.extension_schema)
        cfg = await AppSettingsService(session, settings).get_module_settings()
        await session.rollback()
    return cfg.instance_profile, cfg.module_overrides, cfg.version


async def _check(settings: Settings, tenant: Tenant, *, apply: bool) -> bool:
    """Ein Kunde. ``True``, wenn am Ende Konsole und Kundenschema übereinstimmen."""
    _out(f"\n== {tenant.slug}  (Host {tenant.hostname or '-'}, Schema {tenant.schema_name})")
    if not tenant.console_id:
        _out(
            "   !! Kein Konsolen-Kunde: Eintrag stammt aus MAGISTER_TENANTS, nicht aus der "
            "Konsole. Für ihn gibt es keinen Abgleich."
        )
        return False
    _out(f"   Konsolen-Id        {tenant.console_id}")

    try:
        desired = await fetch_desired_state(
            settings.console_registry_url,
            tenant.console_id,
            token=settings.console_registry_token.get_secret_value(),
            management_marker=settings.console_management_marker.get_secret_value(),
        )
    except DesiredStateUnavailableError as exc:
        _out(f"   !! Soll-Zustand nicht geholt: {_first_line(exc)}")
        return False
    want_profile = desired.settings.get("instance_profile")
    want_switches = desired.settings.get("module_overrides")
    _out(f"   Konsole will       Profil={want_profile}  Module={want_switches}")

    try:
        have_profile, have_switches, version = await _current(settings, tenant)
    except Exception as exc:
        _out(f"   !! Kundenschema nicht lesbar: {_first_line(exc)}")
        return False
    _out(f"   Kundenschema hat   Profil={have_profile}  Module={have_switches}  (v{version})")

    try:
        async with get_engines().sessionmaker_for(tenant)() as session:
            attach_keys(session, tenant_keys(settings, tenant))
            await apply_tenant_scope(session, tenant, extension_schema=settings.extension_schema)
            preview = await Reconciler(session, settings).reconcile(
                desired, tenant_slug=tenant.slug, dry_run=True, tenant_ref=tenant.console_id
            )
            await session.rollback()
    except Exception as exc:
        _out(f"   !! Abgleich (Vorschau) scheitert: {_first_line(exc)}")
        return False
    changed = ", ".join(sorted(preview.changed_settings)) or "keine"
    _out(f"   Abweichende Felder {changed}")
    if preview.unknown_keys:
        _out(f"   Unbekannte Felder  {', '.join(sorted(preview.unknown_keys))}")

    if not apply:
        return want_profile in (None, have_profile)

    try:
        touched = await reconcile_tenant(settings, tenant)
    except Exception as exc:
        _out(f"   !! Abgleich scheitert: {_first_line(exc)}")
        return False
    have_profile, have_switches, version = await _current(settings, tenant)
    _out(
        f"   Nach dem Abgleich  Profil={have_profile}  Module={have_switches}  (v{version})"
        f"{'  — geschrieben' if touched else ''}"
    )
    ok = want_profile in (None, have_profile)
    if not ok:
        _out("   !! Profil stimmt nach dem Abgleich noch immer nicht.")
    return ok


async def _run(args: argparse.Namespace) -> int:
    settings = get_settings()
    if not settings.console_registry_url:
        _out("MAGISTER_CONSOLE_REGISTRY_URL ist nicht gesetzt: keine Konsole, kein Abgleich.")
        return 2
    init_tenancy(settings)
    try:
        if not await refresh_from_console(settings):
            _out("!! Kundenliste der Konsole nicht geholt — es gilt die aus der Umgebung.")
            _out(
                '   Steht oben „fehlt MAGISTER_TENANT_DSN_…": auf dem Host '
                "./scripts/plattform-aufbau.sh kunde-anbinden ausführen."
            )
        tenants = [t for t in get_registry().tenants if not args.kunde or t.slug == args.kunde]
        if not tenants:
            _out(f"Kein Kunde {args.kunde!r} in der Kundenliste.")
            return 2
        results = [await _check(settings, t, apply=not args.nur_zeigen) for t in tenants]
    finally:
        await dispose_tenancy()
    return 0 if all(results) else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m magister_api.cli.abgleich")
    parser.add_argument("--kunde", help="nur diesen Kunden (Kürzel)")
    parser.add_argument("--nur-zeigen", action="store_true", help="nur berichten, nichts schreiben")
    return asyncio.run(_run(parser.parse_args(argv)))


if __name__ == "__main__":
    raise SystemExit(main())
