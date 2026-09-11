"""Mandanten-Werkzeug: auflisten, prüfen, migrieren (ADR-0013 D7, ADR-0016 D6).

Aufruf über ``scripts/magister-cli tenants <aktion>``.

Der Migrations-Runner läuft die Registry ab und macht drei Dinge in dieser
Reihenfolge, pro Mandant:

1. **Dump ziehen, verschlüsselt.** Die Rückfahrkarte (ADR-0016 D6). Ohne sie
   ist eine fehlgeschlagene Migration ein Datenverlust und keine
   Unannehmlichkeit. Überspringen geht nur mit ``--no-dump`` — ausdrücklich,
   nicht versehentlich.

   Verschlüsselt heisst: ``pg_dump | age -r <öffentlicher Schlüssel>`` als
   Kette ohne Zwischendatei, genau wie in der Konsole (ADR-0016 D2). Bis
   ADR-0021 stand hier ein nacktes ``pg_dump --file=…`` — ein Klartext-Dump
   eines Schulschemas auf der Platte, gegen die eigene harte Regel und in
   Code, der im Onboarding-Runbook steht. Ohne ``age`` oder ohne Empfänger
   scheitert der Schritt jetzt, statt Klartext zu hinterlassen.
2. **Kanarienvogel zuerst.** Ein Mandant migriert allein; erst wenn der steht,
   laufen die übrigen. Ein Fehler trifft dann einen Kunden, nicht alle.
3. **Migrieren mit der eigenen Anmelderolle des Mandanten.** Das ist keine
   Kosmetik: migriert man als Superuser, gehören die Tabellen dem Superuser und
   die Mandantenrolle bekommt beim ersten Query „permission denied for table".
   Nachgemessen, nicht vermutet.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy.engine import make_url

from magister_api.cli._migration_record import read_head, record_migration
from magister_api.cli._pipe import PipeError, Stage, run_pipe
from magister_api.config import Settings, get_settings
from magister_api.tenancy.context import build_registry
from magister_api.tenancy.registry import Tenant, TenantConfigError
from magister_api.tenancy.version import HEAD_REVISION

API_DIR = Path(__file__).resolve().parents[2]

#: Öffentlicher age-Schlüssel: ``age1`` plus Bech32. Dasselbe Muster wie in
#: der Konsole — ein leerer oder falsch geformter Empfänger wäre der Weg zu
#: einem unverschlüsselten Dump, und das ist ein Abbruch und keine Warnung.
RECIPIENT_PATTERN = re.compile(r"^age1[0-9a-z]{58}$")

#: Umgebungsvariable mit dem Empfänger. Nur der **öffentliche** Schlüssel: mit
#: ihm lässt sich schreiben und nichts lesen. Wer den Anwendungsserver
#: übernimmt, bekommt damit keinen alten Dump auf.
RECIPIENT_ENV = "MAGISTER_BACKUP_AGE_RECIPIENT"


@dataclass(frozen=True, slots=True)
class StepResult:
    tenant: str
    action: str
    ok: bool
    detail: str = ""
    #: Beim Dump der Dateiname der Rückfahrkarte. Ein eigenes Feld und nicht
    #: der erste Teil von ``detail``: den liest sonst jemand mit ``split(" ")``
    #: auseinander, und dann hängt das Protokoll des Kunden an einer
    #: Formulierung fürs Terminal.
    artifact: str | None = None


def _out(msg: str) -> None:
    # Ein CLI schreibt auf stdout, nicht in den Logger — die Logger-Regel gilt
    # für den Backend-Code im Request-Pfad.
    sys.stdout.write(msg + "\n")
    sys.stdout.flush()


def _libpq_env(dsn: str) -> dict[str, str]:
    """libpq-Umgebung aus einem SQLAlchemy-DSN.

    Das Passwort geht über ``PGPASSWORD`` und nie über argv: Argumente stehen
    in ``ps`` für jeden auf dem Host lesbar.
    """
    url = make_url(dsn)
    env = dict(os.environ)
    if url.host:
        env["PGHOST"] = url.host
    query_host = url.query.get("host")
    if isinstance(query_host, str) and query_host:
        env["PGHOST"] = query_host
    if url.port:
        env["PGPORT"] = str(url.port)
    query_port = url.query.get("port")
    if isinstance(query_port, str) and query_port:
        env["PGPORT"] = query_port
    if url.username:
        env["PGUSER"] = url.username
    if url.password:
        env["PGPASSWORD"] = url.password
    if url.database:
        env["PGDATABASE"] = url.database
    return env


def check_recipient(value: str | None) -> str:
    """Empfänger prüfen. Kein gültiger Schlüssel heisst: kein Dump.

    Absichtlich ein Abbruch und keine Warnung mit Rückfall auf Klartext. Auf
    einem Share ist ein Dump für mehr Personen und Systeme erreichbar als in
    der Datenbank, und ein Schulschema enthält Namen, Klassen und Geburtsdaten
    von Minderjährigen.
    """
    candidate = (value or "").strip()
    if not RECIPIENT_PATTERN.match(candidate):
        raise PipeError(
            f"{RECIPIENT_ENV} ist kein gültiger öffentlicher age-Schlüssel "
            "(erwartet 'age1…'). Ohne ihn würde der Vor-Migrations-Dump "
            "unverschlüsselt auf der Platte liegen — das wird nicht gemacht. "
            "Der Wert ist derselbe wie COCKPIT_BACKUP_AGE_RECIPIENT."
        )
    return candidate


def dump_path(dump_dir: Path, slug: str, when: datetime) -> Path:
    """Ablagepfad. ``.age`` am Ende, damit man am Namen sieht, was es ist."""
    stamp = when.strftime("%Y%m%dT%H%M%SZ")
    return dump_dir / f"{slug}-{stamp}-pre-migration.dump.age"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def dump_tenant(tenant: Tenant, dump_dir: Path, *, recipient: str | None = None) -> StepResult:
    """Verschlüsselter ``pg_dump --schema`` des Mandantenschemas.

    ``pg_dump | age -r …`` als Kette ohne Zwischendatei: eine
    unverschlüsselte Zwischendatei wäre genau das, was die Verschlüsselung
    verhindern soll — und sie läge auch dann da, wenn der Prozess mittendrin
    abbricht.

    Geschrieben wird unter einem Arbeitsnamen und erst am Ende umbenannt.
    Sonst liegt bei einem Abbruch eine halbe Datei da, die aussieht wie ein
    Dump. Die Prüfsumme geht über die **verschlüsselte** Datei — damit lässt
    sich später feststellen, ob sie unverändert ist, ohne sie zu entschlüsseln.
    """
    # Absolute Pfade: dieses Werkzeug läuft auch aus einem Wartungsfenster
    # heraus, in dem PATH nicht der einer Anmeldesitzung ist.
    pg_dump_bin = shutil.which("pg_dump")
    age_bin = shutil.which("age")
    if pg_dump_bin is None:
        return StepResult(tenant.slug, "dump", False, "pg_dump ist nicht installiert")
    if age_bin is None:
        return StepResult(
            tenant.slug,
            "dump",
            False,
            "age ist nicht installiert. Ohne age gibt es keinen verschlüsselten "
            "Dump, und ein unverschlüsselter wird nicht geschrieben.",
        )
    try:
        target_recipient = check_recipient(
            recipient if recipient is not None else os.environ.get(RECIPIENT_ENV)
        )
    except PipeError as exc:
        return StepResult(tenant.slug, "dump", False, str(exc))

    dump_dir.mkdir(parents=True, exist_ok=True)
    target = dump_path(dump_dir, tenant.slug, datetime.now(UTC))
    partial = target.with_suffix(target.suffix + ".partial")
    try:
        run_pipe(
            Stage(
                argv=(
                    pg_dump_bin,
                    "--format=custom",
                    "--no-owner",
                    "--no-privileges",
                    f"--schema={tenant.schema_name}",
                ),
                env=_libpq_env(tenant.dsn),
                label="pg_dump",
            ),
            Stage(argv=(age_bin, "-r", target_recipient), label="age"),
            stdout_path=partial,
        )
    except PipeError as exc:
        partial.unlink(missing_ok=True)
        return StepResult(tenant.slug, "dump", False, str(exc))

    size = partial.stat().st_size
    if size == 0:
        partial.unlink(missing_ok=True)
        return StepResult(tenant.slug, "dump", False, "der Dump ist leer")
    digest = _sha256(partial)
    partial.replace(target)
    return StepResult(
        tenant.slug,
        "dump",
        True,
        f"{target.name} ({size} Bytes, sha256 {digest[:12]}…)",
        artifact=target.name,
    )


def migrate_tenant(tenant: Tenant, *, extension_schema: str) -> StepResult:
    """``alembic upgrade head`` für genau ein Schema."""
    env = dict(os.environ)
    env["MAGISTER_DATABASE_URL"] = tenant.dsn
    env["MAGISTER_MIGRATE_SCHEMA"] = tenant.schema_name
    env["MAGISTER_EXTENSION_SCHEMA"] = extension_schema
    proc = subprocess.run(  # noqa: S603 — feste Argumentliste, keine Shell
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=API_DIR,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        tail = (proc.stderr or proc.stdout or "").strip().splitlines()
        return StepResult(
            tenant.slug, "migrate", False, tail[-1] if tail else "alembic fehlgeschlagen"
        )
    applied = [
        line.split("Running upgrade ", 1)[1]
        for line in (proc.stderr or "").splitlines()
        if "Running upgrade " in line
    ]
    if not applied:
        return StepResult(tenant.slug, "migrate", True, "schon auf dem Kopfstand")
    return StepResult(tenant.slug, "migrate", True, f"{len(applied)} Migration(en)")


def cmd_list(args: argparse.Namespace) -> int:
    registry = build_registry()
    _out(f"{len(registry.tenants)} Mandant(en), Code-Kopf {HEAD_REVISION}")
    for t in registry.tenants:
        host = t.hostname or "(jeder Hostname)"
        role = t.db_role or "(Anmelderolle der Verbindung)"
        version = t.schema_version or "(unbekannt)"
        flag = "" if version in (HEAD_REVISION, "(unbekannt)") else "  << Stand weicht ab"
        _out(
            f"  {t.slug:<20} {host:<28} {t.status.value:<13} "
            f"Schema {t.schema_name:<16} Rolle {role:<22} Stand {version}{flag}"
        )
    return 0


def cmd_migrate(args: argparse.Namespace) -> int:
    settings = get_settings()
    registry = build_registry(settings)
    tenants = list(registry.tenants)
    if args.only:
        tenants = [t for t in tenants if t.slug in set(args.only)]
        if not tenants:
            _out(f"Kein Mandant passt zu --only {args.only}.")
            return 2

    if args.no_dump:
        _out(
            "ACHTUNG: --no-dump. Es wird ohne Rückfahrkarte migriert; eine "
            "fehlgeschlagene Migration ist dann ein Datenverlust (ADR-0016 D6)."
        )
        dump_dir = None
    else:
        if not args.dump_dir:
            _out("--dump-dir fehlt. Entweder ein Zielverzeichnis angeben oder --no-dump.")
            return 2
        dump_dir = Path(args.dump_dir)
        # Vorab und nicht beim ersten Kunden: ein fehlender Empfänger ist ein
        # Konfigurationsfehler, und der soll auffallen, bevor irgendetwas
        # angefasst wurde. Sonst scheitert der Kanarienvogel an etwas, das
        # nichts mit der Migration zu tun hat.
        try:
            check_recipient(args.recipient or os.environ.get(RECIPIENT_ENV))
        except PipeError as exc:
            _out(str(exc))
            return 2

    try:
        canary = _pick_canary(tenants, args.canary)
    except TenantConfigError as exc:
        _out(str(exc))
        return 2
    ordered = [canary, *[t for t in tenants if t.slug != canary.slug]]
    _out(f"Kanarienvogel: {canary.slug}. Danach {len(ordered) - 1} weitere.")

    single_tenant = len(registry.tenants) == 1
    results: list[StepResult] = []
    for index, tenant in enumerate(ordered):
        _out(f"\n--- {tenant.slug} ({index + 1}/{len(ordered)}) ---")
        dump_name: str | None = None
        if dump_dir is not None:
            step = dump_tenant(tenant, dump_dir, recipient=args.recipient or None)
            results.append(step)
            _out(f"  Dump:     {'ok' if step.ok else 'FEHLER'}  {step.detail}")
            if not step.ok:
                _out("  Migration übersprungen — ohne Dump wird hier nicht migriert.")
                if _stop_after_failure(index, args.keep_going):
                    break
                continue
            dump_name = step.artifact
        # Vorher-Stand VOR der Migration, sonst ist er hinterher nicht mehr
        # feststellbar. Scheitert das Lesen, steht im Protokoll „unbekannt";
        # das ist kein Grund, nicht zu migrieren.
        before = asyncio.run(read_head(tenant, settings))
        step = migrate_tenant(tenant, extension_schema=settings.extension_schema)
        results.append(step)
        _out(f"  Migration: {'ok' if step.ok else 'FEHLER'}  {step.detail}")
        if not step.ok and _stop_after_failure(index, args.keep_going):
            break
        if step.ok:
            _record(tenant, settings, before=before, dump=dump_name, single=single_tenant)
        if index == 0 and len(ordered) > 1 and args.canary_only:
            _out("\n--canary-only: hier ist Schluss. Nach der Prüfung ohne Flag erneut starten.")
            break

    failed = [r for r in results if not r.ok]
    _out("")
    _out(f"{len(results) - len(failed)} Schritt(e) ok, {len(failed)} Fehler.")
    for r in failed:
        _out(f"  FEHLER {r.tenant}/{r.action}: {r.detail}")
    return 1 if failed else 0


def _record(
    tenant: Tenant, settings: Settings, *, before: str | None, dump: str | None, single: bool
) -> None:
    """Ereignis und Standmeldung — und was davon nicht geklappt hat.

    Kein Rückgabewert und kein `StepResult`: das hier ist **kein** Schritt,
    der den Lauf zum Scheitern bringen kann. Die Migration ist gelaufen; was
    hier fehlschlägt, ist eine fehlende Notiz und kein fehlendes Schema.
    """
    outcome = asyncio.run(
        record_migration(tenant, settings, before=before, dump=dump, single_tenant=single)
    )
    stand = outcome.head or "unbekannt"
    marks = []
    marks.append("Protokoll ok" if outcome.audited else "ohne Protokoll")
    marks.append("gemeldet" if outcome.reported else "nicht gemeldet")
    _out(f"  Stand:     {stand}  ({', '.join(marks)})")
    for note in outcome.notes:
        _out(f"    Hinweis: {note}")


def _stop_after_failure(index: int, keep_going: bool) -> bool:
    """Nach einem Fehler weitermachen oder anhalten?

    Standard ist anhalten. Beim Kanarienvogel ist es sogar zwingend: er
    existiert genau dafür, dass ein Fehler einen Kunden trifft und nicht
    vierzig. ``--keep-going`` gilt deshalb bewusst nicht für ihn — wer den
    ersten Mandanten nicht migrieren kann, soll nicht die Flotte anfassen.
    """
    if index == 0:
        _out("\nAbbruch: der Kanarienvogel ist gescheitert. Die übrigen Mandanten")
        _out("bleiben unangetastet — genau dafür gibt es ihn.")
        return True
    if keep_going:
        _out("  --keep-going: weiter mit dem nächsten Mandanten.")
        return False
    _out("\nAbbruch: ein Mandant ist gescheitert, die übrigen bleiben unangetastet.")
    _out("Mit --keep-going würde der Lauf trotzdem weitergehen.")
    return True


def _pick_canary(tenants: list[Tenant], requested: str | None) -> Tenant:
    if requested:
        for t in tenants:
            if t.slug == requested:
                return t
        raise TenantConfigError(f"Kanarienvogel {requested!r} steht nicht in der Registry.")
    return tenants[0]


def add_parser(subparsers: argparse._SubParsersAction) -> None:  # type: ignore[type-arg]
    parser = subparsers.add_parser(
        "tenants",
        help="Mandanten auflisten und migrieren",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    actions = parser.add_subparsers(dest="action", required=True)

    listing = actions.add_parser("list", help="Registry anzeigen")
    listing.set_defaults(func=cmd_list)

    migrate = actions.add_parser(
        "migrate", help="alembic upgrade head pro Mandant, mit Dump und Kanarienvogel"
    )
    migrate.add_argument("--dump-dir", help="Zielverzeichnis für die Vor-Migrations-Dumps")
    migrate.add_argument(
        "--recipient",
        default=None,
        help=f"öffentlicher age-Schlüssel für die Dumps; sonst aus ${RECIPIENT_ENV}",
    )
    migrate.add_argument(
        "--no-dump",
        action="store_true",
        help="ohne Dump migrieren (ausdrücklich gewollt, nicht empfohlen)",
    )
    migrate.add_argument("--canary", help="Slug des Mandanten, der zuerst migriert wird")
    migrate.add_argument(
        "--canary-only",
        action="store_true",
        help="nach dem Kanarienvogel anhalten",
    )
    migrate.add_argument("--only", nargs="+", metavar="SLUG", help="nur diese Mandanten migrieren")
    migrate.add_argument(
        "--keep-going",
        action="store_true",
        help="nach einem Fehler mit dem nächsten Mandanten weitermachen "
        "(gilt nicht für den Kanarienvogel)",
    )
    migrate.set_defaults(func=cmd_migrate)
