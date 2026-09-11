"""Periodischer AD-Abgleich — je Kunde, versetzt, isoliert (ADR-0021 D4).

Der manuelle :http:post:`/ad/sync` bleibt; dies ist die wiederkehrende Hälfte.
Gestartet und gestoppt wird die Schleife vom FastAPI-Lebenszyklus.

**Was hier bis ADR-0021 falsch war:** die Schleife nahm *eine* Sitzung aus der
Prozess-Engine (`MAGISTER_DATABASE_URL`) und synchronisierte damit genau ein
Schema. Bei einem Kunden ist das dasselbe; bei zwei synchronisierte sie einen
und liess den anderen liegen — und zwar still. Der Hinweis stand seit Phase 1
im Docstring von `db.py` („der Fan-out kommt mit der Konsole in Phase 2“) und
ist dort liegen geblieben.

Jetzt dasselbe Muster wie beim Abgleich des Soll-Zustands
(`services/reconcile_loop.py`):

* **Eine Sitzung je Kunde**, aus der Engine dieses Kunden, mit seinem
  Schlüssel und seinem `search_path`.
* **Ein eigenes `try` je Kunde.** Ein Kunde mit unerreichbarem
  Domänencontroller hält die anderen nicht auf.
* **Das Intervall aus den wirksamen Einstellungen dieses Kunden**, nicht aus
  einer globalen Zahl. Ein Kunde mit 15 Minuten und einer mit 60 sind zwei
  Fahrpläne, kein Kompromiss.
* **Versetzte Startzeiten**, deterministisch über die Reihenfolge in der
  Registry: Kunde *i* von *n* startet bei *i·Intervall/n*. Nicht zufällig —
  ein Zufallsversatz ist im Log nicht nachvollziehbar, und die Frage „warum
  hat Kunde 7 um 04:13 synchronisiert“ soll eine Antwort haben. Der Versatz
  schont nicht die Datenbank, sondern die Domänencontroller der Kunden und
  den Connector-Kanal.

Die Schleife wacht in kurzen Schritten auf und fragt, wer fällig ist. Das ist
billiger als es aussieht (ein `SELECT` je Runde entsteht nur für fällige
Kunden) und erlaubt pro Kunde ein eigenes Intervall, ohne für jeden eine
eigene Task zu halten.

Vor der AD-Konfiguration (Erstinbetriebnahme) werden Runden übersprungen.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import Callable

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from magister_api.ad.client import AdClient
from magister_api.ad.errors import AdUnavailableError
from magister_api.auth.effective_settings import load_effective_settings
from magister_api.config import Settings
from magister_api.services.ad_sync import AdSyncService
from magister_api.tenancy.context import get_engines, get_registry
from magister_api.tenancy.keys import attach_keys, resolve_tenant_keys
from magister_api.tenancy.registry import Tenant, TenantRegistry
from magister_api.tenancy.scope import apply_tenant_scope

logger = logging.getLogger(__name__)

SCHEDULER_ACTOR_UPN = "system:ad-sync-scheduler"

#: Wie oft die Schleife nachsieht, wer fällig ist. Klein gegenüber jedem
#: sinnvollen Sync-Intervall (Minimum ist eine Minute) und gross genug, dass
#: das Nachsehen nichts kostet.
TICK_SECONDS = 5.0

#: Typ der Sitzungsfabrik je Mandant. Injizierbar, damit ein Test nicht die
#: Prozess-Globalen aus `tenancy.context` aufbauen muss — dieselbe Bauart wie
#: `read_registry` in der Auflösungs-Middleware.
SessionFactoryFor = Callable[[Tenant], async_sessionmaker[AsyncSession]]


def _ad_configured(settings: Settings) -> bool:
    """True, wenn ein Abgleich überhaupt versucht werden kann.

    Beide Betriebsarten brauchen eine Suchbasis — ohne sie wirft
    ``search_users`` sofort. Der Live-Betrieb braucht zusätzlich einen DC; der
    Mock-Betrieb (Tests) nicht.
    """
    if not settings.ad_users_search_base:
        return False
    return settings.ad_use_mock or bool(settings.ad_dcs)


def _default_session_factory(tenant: Tenant) -> async_sessionmaker[AsyncSession]:
    return get_engines().sessionmaker_for(tenant)


async def _run_tick(
    session: AsyncSession,
    settings: Settings,
    client_factory: Callable[[Settings], AdClient],
) -> None:
    ad = client_factory(settings)
    try:
        # request_id ist VARCHAR(36); actor_upn markiert die Herkunft schon.
        await AdSyncService(session, settings, ad).sync_all(
            actor_upn=SCHEDULER_ACTOR_UPN,
            actor_object_guid=None,
            ip=None,
            request_id=uuid.uuid4().hex,
        )
    finally:
        await ad.aclose()


async def sync_tenant(
    base_settings: Settings,
    tenant: Tenant,
    *,
    client_factory: Callable[[Settings], AdClient] = AdClient,
    session_factory: SessionFactoryFor = _default_session_factory,
    single_tenant: bool,
) -> int:
    """Einen Kunden abgleichen. Gibt dessen Intervall in Minuten zurück.

    Das Intervall kommt aus **seinen** wirksamen Einstellungen und wird auch
    dann geliefert, wenn der Abgleich übersprungen wurde — der Fahrplan hängt
    nicht daran, ob eine Runde etwas getan hat.
    """
    interval = max(1, base_settings.ad_sync_interval_minutes)
    keys = resolve_tenant_keys(
        tenant.slug,
        fallback_audit_key=base_settings.audit_key.get_secret_value(),
        fallback_audit_key_id=base_settings.audit_key_id,
        fallback_secrets_key=base_settings.app_secrets_key(),
        single_tenant=single_tenant,
    )
    sm = session_factory(tenant)
    async with sm() as session:
        # Schlüssel und Scope vor dem ersten Query: der Abgleich schreibt
        # Audit-Ereignisse, und die sind mit dem Kundenschlüssel verschlüsselt.
        attach_keys(session, keys)
        await apply_tenant_scope(session, tenant, extension_schema=base_settings.extension_schema)
        settings = await load_effective_settings(session, base_settings)
        interval = max(1, settings.ad_sync_interval_minutes)
        if not _ad_configured(settings):
            logger.debug("AD für %s nicht konfiguriert — Runde übersprungen", tenant.slug)
            await session.rollback()
            return interval
        try:
            await _run_tick(session, settings, client_factory)
        except AdUnavailableError as exc:
            logger.warning(
                "Geplanter AD-Abgleich für %s: AD nicht erreichbar (%s)", tenant.slug, exc
            )
        # In beiden Fällen committen: bei Erfolg die Cache-Zeilen und
        # `ad_sync_completed`, sonst die Zeile `ad_sync_failed`.
        await session.commit()
    return interval


def _initial_due(now: float, tenants: list[Tenant], interval_minutes: int) -> dict[str, float]:
    """Startzeitpunkte, über das Intervall verteilt.

    Der erste Kunde läuft sofort. Der Versatz ist Absicht und nicht Vorsicht:
    zehn gleichzeitige Vollsynchronisationen sind eine Last, die sich ohne Not
    auf zehn Zeitpunkte verteilen lässt.
    """
    if not tenants:
        return {}
    spread = (max(1, interval_minutes) * 60.0) / len(tenants)
    return {tenant.slug: now + index * spread for index, tenant in enumerate(tenants)}


async def run_ad_sync_loop(
    base_settings: Settings,
    *,
    stop_event: asyncio.Event,
    client_factory: Callable[[Settings], AdClient] = AdClient,
    read_registry: Callable[[], TenantRegistry] = get_registry,
    session_factory: SessionFactoryFor = _default_session_factory,
) -> None:
    """Bis ``stop_event`` gesetzt ist: wer fällig ist, wird abgeglichen."""
    logger.info("AD-Abgleich-Schleife gestartet")
    loop = asyncio.get_running_loop()
    due: dict[str, float] = {}
    known: set[str] = set()

    while not stop_event.is_set():
        try:
            tenants = list(read_registry().tenants)
            single = len(tenants) == 1
            current = {t.slug for t in tenants}
            if current != known:
                # Der Fahrplan wird nur bei der ERSTEN Runde verteilt. Danach
                # gilt: wer schon einen Zeitpunkt hat, behält ihn (sonst
                # verschiebt jeder neue Kunde die Termine aller anderen), und
                # ein neu aufgetauchter ist **sofort** fällig. Ihn auf einen
                # Platz in der Verteilung zu setzen, wäre eine Wartezeit von
                # bis zu einem Intervall für einen Kunden, der gerade
                # dazugekommen ist und noch gar keine Daten hat.
                if not known:
                    due = _initial_due(
                        loop.time(), tenants, base_settings.ad_sync_interval_minutes
                    )
                else:
                    due = {t.slug: due.get(t.slug, loop.time()) for t in tenants}
                known = current

            now = loop.time()
            for tenant in tenants:
                if stop_event.is_set():
                    break
                if now < due.get(tenant.slug, 0.0):
                    continue
                try:
                    interval = await sync_tenant(
                        base_settings,
                        tenant,
                        client_factory=client_factory,
                        session_factory=session_factory,
                        single_tenant=single,
                    )
                except Exception:
                    # Jeder Kunde in seinem eigenen `try`: einer, der
                    # stolpert, hält die anderen nicht auf. Und der Fahrplan
                    # rückt trotzdem vor — sonst versucht es die Schleife
                    # alle fünf Sekunden erneut.
                    logger.exception("Geplanter AD-Abgleich für %s gescheitert", tenant.slug)
                    interval = max(1, base_settings.ad_sync_interval_minutes)
                due[tenant.slug] = loop.time() + interval * 60.0
        except Exception:
            # Eine schlechte Runde darf die Schleife nicht töten.
            logger.exception("Runde der AD-Abgleich-Schleife gescheitert")

        try:
            await asyncio.wait_for(stop_event.wait(), timeout=TICK_SECONDS)
        except TimeoutError:
            continue
    logger.info("AD-Abgleich-Schleife gestoppt")


__all__ = [
    "SCHEDULER_ACTOR_UPN",
    "TICK_SECONDS",
    "run_ad_sync_loop",
    "sync_tenant",
]
