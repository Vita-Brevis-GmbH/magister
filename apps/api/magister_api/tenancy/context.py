"""Registry-Aufbau und Zugriff auf den Mandanten der laufenden Anfrage.

Wie ``db.py`` hält dieses Modul Prozess-Globale und wird beim Start
initialisiert. Es gibt bewusst **keinen** Umschalter zwischen Ein- und
Mehrmandantenbetrieb (ADR-0013 D8): fehlt ``MAGISTER_TENANTS``, entsteht eine
Registry mit genau einer Zeile aus ``MAGISTER_DATABASE_URL``. Derselbe
Anfragepfad, dieselbe Auflösung, dieselbe Sitzungs-Einrichtung — nur n=1.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from starlette.requests import Request

from magister_api.config import Settings, get_settings
from magister_api.tenancy.console_registry import (
    ConsoleUnavailableError,
    fetch_registry,
)
from magister_api.tenancy.engines import TenantEngineRegistry
from magister_api.tenancy.registry import (
    Tenant,
    TenantConfigError,
    TenantRegistry,
    registry_from_json,
    single_tenant_registry,
)

logger = logging.getLogger(__name__)

#: Attribut, unter dem die Middleware den aufgelösten Mandanten ablegt.
REQUEST_STATE_ATTR = "tenant"

_registry: TenantRegistry | None = None
_engines: TenantEngineRegistry | None = None


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
    global _registry
    s = settings or get_settings()
    if not s.console_registry_url:
        return False
    try:
        fresh = await fetch_registry(
            s.console_registry_url,
            token=s.console_registry_token.get_secret_value(),
            management_marker=s.console_management_marker.get_secret_value(),
        )
    except (ConsoleUnavailableError, TenantConfigError) as exc:
        # WARNING, nicht ERROR: der Betrieb läuft weiter. Aber sichtbar, denn
        # ein neu angelegter Kunde kommt bis zur Behebung nicht durch.
        logger.warning("Konsolen-Registry nicht übernommen, letzter guter Stand bleibt: %s", exc)
        return False
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
        try:
            await asyncio.wait_for(stop.wait(), timeout=s.console_registry_interval_s)
        except TimeoutError:
            continue


async def dispose_tenancy() -> None:
    global _registry, _engines
    if _engines is not None:
        await _engines.dispose_all()
    _registry = None
    _engines = None


def tenant_from_request(request: Request) -> Tenant:
    tenant = getattr(request.state, REQUEST_STATE_ATTR, None)
    if not isinstance(tenant, Tenant):
        raise TenantNotResolvedError(
            "Kein Mandant an dieser Anfrage. Fehlt die TenantResolutionMiddleware in create_app()?"
        )
    return tenant
