"""Registry-Aufbau und Zugriff auf den Mandanten der laufenden Anfrage.

Wie ``db.py`` hält dieses Modul Prozess-Globale und wird beim Start
initialisiert. Es gibt bewusst **keinen** Umschalter zwischen Ein- und
Mehrmandantenbetrieb (ADR-0013 D8): fehlt ``MAGISTER_TENANTS``, entsteht eine
Registry mit genau einer Zeile aus ``MAGISTER_DATABASE_URL``. Derselbe
Anfragepfad, dieselbe Auflösung, dieselbe Sitzungs-Einrichtung — nur n=1.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from starlette.requests import Request

from magister_api.config import Settings, get_settings
from magister_api.tenancy.console_registry import (
    ConsoleUnavailableError,
    fetch_registry,
    registry_from_console_payload,
)
from magister_api.tenancy.engines import TenantEngineRegistry
from magister_api.tenancy.registry import (
    Tenant,
    TenantConfigError,
    TenantRegistry,
    TenantStatus,
    registry_from_json,
    single_tenant_registry,
)

logger = logging.getLogger(__name__)

#: Attribut, unter dem die Middleware den aufgelösten Mandanten ablegt.
REQUEST_STATE_ATTR = "tenant"

_registry: TenantRegistry | None = None
_engines: TenantEngineRegistry | None = None
#: Hat dieser Prozess die Konsole schon einmal erreicht (oder ihren
#: Zwischenstand geladen)? Bis dahin fragt die Schleife in kurzen Abständen.
_console_seen = False

#: Wie oft die Schleife fragt, solange die Konsole noch nie geantwortet hat —
#: nach einem Neustart des Hosts kommt sie oft erst nach der Datenebene hoch.
STARTUP_RETRY_S = 15


class TenantNotResolvedError(RuntimeError):
    """Es wurde eine Sitzung angefordert, ohne dass ein Mandant aufgelöst wurde.

    Ein Programmierfehler, kein Betriebszustand: die Auflösungs-Middleware
    gehört in jede Anwendung, und ohne sie wüsste die Sitzung nicht, wessen
    Daten sie öffnen darf. Deshalb ein Abbruch und keine Rückfallebene — eine
    Rückfallebene wäre der ungetestete zweite Codepfad, den ADR-0013 D8
    ausdrücklich nicht will.
    """


def build_registry(settings: Settings | None = None) -> TenantRegistry:
    """Registry aus der Umgebung. Der Konsolen-Abruf läuft getrennt (asynchron).

    Diese Funktion ist die **Grundlage**: sie liefert den Stand, mit dem der
    Prozess startet, auch wenn die Konsole nicht antwortet. Ist eine Konsole
    konfiguriert, überschreibt ``refresh_from_console()`` das Ergebnis, sobald
    ein Abruf geglückt ist.
    """
    s = settings or get_settings()
    raw = (s.tenants or "").strip()
    if not raw and s.console_registry_url:
        # Gehostet, und die Konsole hat noch nicht geantwortet. Der Ersatz-
        # Mandant auf `public` darf dann **niemanden** bedienen: er fängt jeden
        # Hostnamen auf, und ein Kunde landete in einem Schema, das nicht
        # seines ist. Genau das lief auf dem Dev-Host, solange die Datenebene
        # der Konsole nicht traute — Einstellungen aus der Konsole kamen nie
        # an, weil das Portal gar nicht im Schema des Kunden lief.
        # `provisioning` heisst: 503 Wartung, bis die Kundenliste da ist.
        logger.warning(
            "Gehosteter Betrieb ohne Kundenliste: bis die Konsole antwortet, wird "
            "kein Mandant bedient (503). MAGISTER_CONSOLE_REGISTRY_URL=%s",
            s.console_registry_url,
        )
        return single_tenant_registry(dsn=s.database_url, status=TenantStatus.PROVISIONING)
    if not raw:
        registry = single_tenant_registry(dsn=s.database_url)
        logger.info(
            "Mandanten-Registry aus MAGISTER_DATABASE_URL aufgebaut (ein Mandant, "
            "Schema 'public'). MAGISTER_TENANTS ist nicht gesetzt."
        )
        return registry
    registry = registry_from_json(raw, default_dsn=s.database_url)
    logger.info(
        "Mandanten-Registry aus MAGISTER_TENANTS aufgebaut: %d Mandant(en) [%s]",
        len(registry.tenants),
        ", ".join(t.slug for t in registry.tenants),
    )
    return registry


def init_tenancy(
    settings: Settings | None = None, **engine_kwargs: Any
) -> tuple[TenantRegistry, TenantEngineRegistry]:
    """Registry und Engines aufbauen. Einmal beim Start, dann unveränderlich."""
    global _registry, _engines
    s = settings or get_settings()
    _registry = build_registry(s)
    _engines = TenantEngineRegistry(
        pool_size=s.tenant_pool_size,
        max_overflow=s.tenant_max_overflow,
        engine_kwargs=engine_kwargs,
    )
    return _registry, _engines


def get_registry() -> TenantRegistry:
    """Registry holen, notfalls aufbauen.

    Dieselbe Nachsicht wie ``db.get_engine()``: wer ohne Lifespan läuft (Tests,
    ein CLI-Aufruf), bekommt die Registry aus denselben Einstellungen statt
    einer Ausnahme. Das ist kein zweiter Codepfad — es ist derselbe Aufbau,
    nur später. Eine unbrauchbare Konfiguration bricht den Start trotzdem ab,
    weil der Lifespan ``init_tenancy()`` ausdrücklich aufruft.
    """
    if _registry is None:
        init_tenancy()
    assert _registry is not None
    return _registry


def get_engines() -> TenantEngineRegistry:
    if _engines is None:
        init_tenancy()
    assert _engines is not None
    return _engines


async def refresh_from_console(settings: Settings | None = None) -> bool:
    """Registry von der Konsole nachladen. ``True``, wenn sie ersetzt wurde.

    Scheitert der Abruf, bleibt der bisherige Stand **unverändert** in Kraft.
    Das ist die Zusage aus ADR-0013 D4: eine Störung in der Verwaltung ist
    kein Ausfall des Betriebs.
    """
    global _registry, _console_seen
    s = settings or get_settings()
    if not s.console_registry_url:
        return False
    try:
        fresh = await fetch_registry(
            s.console_registry_url,
            token=s.console_registry_token.get_secret_value(),
            management_marker=s.console_management_marker.get_secret_value(),
            on_payload=lambda payload: _write_cache(s, payload),
        )
    except (ConsoleUnavailableError, TenantConfigError) as exc:
        # WARNING, nicht ERROR: der Betrieb läuft weiter. Aber sichtbar, denn
        # ein neu angelegter Kunde kommt bis zur Behebung nicht durch.
        logger.warning("Konsolen-Registry nicht übernommen, letzter guter Stand bleibt: %s", exc)
        # Gleich nach dem Start gibt es keinen "letzten guten Stand" im
        # Speicher — dann den auf der Platte. Sonst stünde nach jedem
        # Neustart des Hosts jede Kundenseite still, bis die Konsole da ist.
        if not _console_seen:
            _console_seen = _load_cache(s)
        return False
    _console_seen = True
    previous = {t.slug for t in _registry.tenants} if _registry is not None else set()
    _registry = fresh
    current = {t.slug for t in fresh.tenants}
    if previous != current:
        logger.info(
            "Mandanten-Registry von der Konsole aktualisiert: %d Mandant(en) [%s]",
            len(fresh.tenants),
            ", ".join(sorted(current)),
        )
    return True


async def console_refresh_loop(
    settings: Settings | None = None, *, stop: asyncio.Event | None = None
) -> None:
    """Hintergrundschleife für den Konsolen-Abruf.

    Bewusst im Hintergrund und nicht im Anfragepfad: ein Kunden-Request darf
    nie von der Erreichbarkeit der Konsole abhängen.
    """
    s = settings or get_settings()
    if not s.console_registry_url:
        return
    stop = stop or asyncio.Event()
    while not stop.is_set():
        await refresh_from_console(s)
        # Bis zur ersten Antwort kurz takten: nach einem Neustart des Hosts
        # ist die Konsole oft noch nicht oben, und fünf Minuten ohne
        # Kundenliste wären fünf Minuten Ausfall.
        wait = (
            s.console_registry_interval_s
            if _console_seen
            else min(STARTUP_RETRY_S, s.console_registry_interval_s)
        )
        try:
            await asyncio.wait_for(stop.wait(), timeout=wait)
        except TimeoutError:
            continue


def _write_cache(settings: Settings, payload: list[dict[str, Any]]) -> None:
    """Die Antwort der Konsole auf die Platte legen (atomar, nur für uns lesbar).

    Darin steht, was die Konsole an die Datenebene schickt: Kürzel,
    Hostnamen, Schemas, Status — keine DSN, keine Passwörter (die kommen aus
    der Umgebung). Ein Fehler hier ist kein Fehler des Abrufs.
    """
    path = settings.console_registry_cache
    if not path:
        return
    target = Path(path)
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=target.parent, prefix=".registry-")
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(payload, fh)
        os.chmod(tmp, 0o600)
        os.replace(tmp, target)
    except OSError as exc:
        logger.warning("Zwischenstand der Kundenliste nicht geschrieben (%s): %s", path, exc)


def _load_cache(settings: Settings) -> bool:
    """Den letzten Stand der Konsole von der Platte übernehmen. ``True`` bei Erfolg."""
    global _registry
    path = settings.console_registry_cache
    if not path or not Path(path).is_file():
        return False
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        cached = registry_from_console_payload(payload)
    except (OSError, ValueError, TenantConfigError) as exc:
        logger.warning("Zwischenstand der Kundenliste unbrauchbar (%s): %s", path, exc)
        return False
    _registry = cached
    stamp = datetime.fromtimestamp(Path(path).stat().st_mtime, UTC).isoformat(timespec="seconds")
    logger.warning(
        "Konsole nicht erreichbar — Kundenliste aus dem Zwischenstand vom %s: %d Mandant(en). "
        "Neue oder geänderte Kunden kommen erst mit der Konsole.",
        stamp,
        len(cached.tenants),
    )
    return True


async def dispose_tenancy() -> None:
    global _registry, _engines, _console_seen
    if _engines is not None:
        await _engines.dispose_all()
    _registry = None
    _engines = None
    _console_seen = False


def tenant_from_request(request: Request) -> Tenant:
    tenant = getattr(request.state, REQUEST_STATE_ATTR, None)
    if not isinstance(tenant, Tenant):
        raise TenantNotResolvedError(
            "Kein Mandant an dieser Anfrage. Fehlt die TenantResolutionMiddleware in create_app()?"
        )
    return tenant
