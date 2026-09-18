"""Die Schleife, die den Soll-Zustand holt und materialisiert (ADR-0017 D3).

Getrennt vom Reconciler selbst, damit der ohne Netz und ohne Schleife
getestet werden kann — und weil hier die Fragen des Betriebs stehen: wie oft,
in welchem Container, und was passiert, wenn ein Kunde stolpert.

**In jedem Container.** Wie der Registry-Abruf und anders als der AD-Sync: es
ist ein Lesevorgang gegen die Konsole und ein Abgleich, der nichts tut, wenn
schon abgeglichen ist. Zwei Container, die dasselbe feststellen, schreiben
nichts zweimal — der erste findet die Differenz, der zweite findet keine.

**Ein stolpernder Kunde hält die anderen nicht auf.** Jeder Mandant in seinem
eigenen `try`. Ein Kunde mit fehlendem Kundenschlüssel oder unerreichbarem
Schema darf nicht dazu führen, dass die restlichen ihre Konfiguration nicht
bekommen.
"""

from __future__ import annotations

import asyncio
import logging

from magister_api.config import Settings, get_settings
from magister_api.services.reconciler import Reconciler
from magister_api.tenancy.context import get_engines, get_registry
from magister_api.tenancy.desired_state import (
    DesiredStateUnavailableError,
    fetch_desired_state,
)
from magister_api.tenancy.keys import attach_keys, resolve_tenant_keys
from magister_api.tenancy.registry import Tenant
from magister_api.tenancy.scope import apply_tenant_scope

logger = logging.getLogger(__name__)


async def reconcile_tenant(settings: Settings, tenant: Tenant) -> bool:
    """Einen Kunden abgleichen. ``True``, wenn etwas geschrieben wurde.

    Der Soll-Zustand wird **vor** der Datenbanksitzung geholt: scheitert der
    Abruf, wird keine Transaktion geöffnet, und der geltende Stand bleibt
    unangetastet.
    """
    if not tenant.console_id:
        # Ein Kunde aus der Umgebung (MAGISTER_TENANTS) hat keine Konsolen-Id.
        # Für ihn gibt es keinen Soll-Zustand — und das ist kein Fehler,
        # sondern die Einzelinstallation.
        return False
    try:
        desired = await fetch_desired_state(
            settings.console_registry_url,
            tenant.console_id,
            token=settings.console_registry_token.get_secret_value(),
            management_marker=settings.console_management_marker.get_secret_value(),
        )
    except DesiredStateUnavailableError as exc:
        # WARNING, nicht ERROR: der Betrieb läuft mit dem letzten guten Stand
        # weiter (ADR-0017 D3). Sichtbar muss es sein, denn eine Änderung in
        # der Konsole kommt bis zur Behebung nicht an.
        logger.warning(
            "Soll-Zustand für %s nicht geholt, letzter Stand bleibt: %s", tenant.slug, exc
        )
        return False

    keys = resolve_tenant_keys(
        tenant.slug,
        fallback_audit_key=settings.audit_key.get_secret_value(),
        fallback_audit_key_id=settings.audit_key_id,
        fallback_secrets_key=settings.app_secrets_key(),
        single_tenant=len(get_registry().tenants) == 1,
    )
    sm = get_engines().sessionmaker_for(tenant)
    async with sm() as session:
        # Der Kundenschlüssel gehört an die Sitzung, weil der Audit-Dienst ihn
        # braucht: der Abgleich schreibt ein Ereignis, und das ist verschlüsselt.
        attach_keys(session, keys)
        await apply_tenant_scope(session, tenant, extension_schema=settings.extension_schema)
        result = await Reconciler(session, settings).reconcile(desired, tenant_slug=tenant.slug)
        if result.touched:
            await session.commit()
        else:
            # Nichts geschrieben: die Transaktion trotzdem beenden, damit die
            # Verbindung nicht mit einer offenen Transaktion in den Pool
            # zurückgeht ("idle in transaction" hält Sperren und blockiert
            # Migrationen).
            await session.rollback()
        return result.touched


async def reconcile_all(settings: Settings | None = None) -> int:
    """Alle Mandanten abgleichen. Gibt zurück, bei wie vielen etwas geschah."""
    s = settings or get_settings()
    if not s.console_registry_url:
        return 0
    touched = 0
    for tenant in get_registry().tenants:
        try:
            if await reconcile_tenant(s, tenant):
                touched += 1
        except Exception:
            # Jeder Kunde in seinem eigenen try: einer, der stolpert, hält die
            # anderen nicht auf. `exception` und nicht `warning` — hier ist
            # etwas kaputt und nicht bloss unerreichbar.
            logger.exception("Abgleich für %s gescheitert", tenant.slug)
    return touched


async def reconcile_loop(
    settings: Settings | None = None, *, stop: asyncio.Event | None = None
) -> None:
    """Hintergrundschleife für den Abgleich.

    Dasselbe Intervall wie der Registry-Abruf: die beiden gehören zusammen —
    ein neuer Kunde in der Registry braucht seine Einstellungen, und ein
    Kunde, der aus der Registry verschwindet, soll nicht weiter abgeglichen
    werden. Ein eigenes Intervall wäre eine zweite Zahl, die mit der ersten
    auseinanderläuft.
    """
    s = settings or get_settings()
    if not s.console_registry_url:
        return
    stop = stop or asyncio.Event()
    while not stop.is_set():
        try:
            await reconcile_all(s)
        except Exception:
            # Eine schlechte Runde darf die Schleife nicht töten.
            logger.exception("Abgleich-Runde gescheitert")
        try:
            await asyncio.wait_for(stop.wait(), timeout=s.console_registry_interval_s)
        except TimeoutError:
            continue


__all__ = ["reconcile_all", "reconcile_loop", "reconcile_tenant"]
