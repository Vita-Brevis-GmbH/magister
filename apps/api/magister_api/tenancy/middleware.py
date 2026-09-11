"""Auflösung des Mandanten aus dem Hostnamen (ADR-0013 D3, Anfragepfad Schritt 2).

Vor allem anderen: unbekannter Hostname → 404, nicht aktiv → 503, Schema-Stand
≠ Kopf-Version des Codes → 503 Wartung. Erst danach darf überhaupt eine
Sitzung geöffnet werden.

Warum 404 und nicht 400 bei unbekanntem Hostnamen: eine Antwort, die zwischen
„gibt es nicht" und „gibt es, aber nicht für dich" unterscheidet, verrät die
Kundenliste. Wer die Slugs kennt, kennt die Kunden von Vita Brevis.

Warum die Versions-Schranke: ein Schema, das noch nicht auf dem Stand des Codes
ist, beantwortet Abfragen nicht falsch — es beantwortet sie **plausibel** falsch,
mit fehlenden Spalten oder stillen Vorgabewerten. 503 mit Wartungshinweis ist
die ehrlichere Antwort (ADR-0013 D7).

Und derselbe Gedanke beim fehlenden Kundenschlüssel (ADR-0016 D8): ohne ihn
liesse sich zwar lesen, aber kein Audit-Ereignis schreiben — die Anwendung
würde also erst mitten in der ersten Mutation abbrechen. 503 **vor** der ersten
Abfrage sagt dasselbe, nur früher und ohne halbe Vorgänge. Geprüft wird hier
pro Anfrage und nicht beim Start, damit ein neu angelegter Kunde ohne Schlüssel
nicht die laufende Installation aller anderen mitnimmt.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable

from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from magister_api.config import Settings, get_settings
from magister_api.tenancy.context import REQUEST_STATE_ATTR, get_registry
from magister_api.tenancy.keys import TenantKeyError, resolve_tenant_keys
from magister_api.tenancy.registry import Tenant, TenantRegistry
from magister_api.tenancy.version import HEAD_REVISION

logger = logging.getLogger(__name__)

#: Pfade, die ohne Mandanten beantwortet werden. Bewusst kurz: das sind die
#: internen Sonden, die auch bei einem kaputten Registry-Eintrag noch
#: antworten müssen, damit ein Orchestrierer den Container nicht endlos neu
#: startet, während er nur eine Zeile Konfiguration braucht.
#:
#: `/healthz/stack` steht hier, weil es sonst **genau dann** schweigt, wenn es
#: gebraucht wird: ein Mandant mit abweichendem Schemastand oder fehlendem
#: Schlüssel bekommt von dieser Middleware ein `503 maintenance`, und die
#: Sonde dahinter käme nie zum Zug. Sie löst den Mandanten selbst auf und
#: verlangt einen eigenen Token.
TENANT_FREE_PATHS: frozenset[str] = frozenset({"/healthz", "/runtime", "/healthz/stack"})


def resolve_host(request: Request) -> str | None:
    """Hostname der Anfrage — ``X-Forwarded-Host`` vor ``Host``.

    Caddy setzt ``X-Forwarded-Host`` (siehe ADR-0013 D3). Der Wert ist damit
    proxy-gesetzt und nicht clientkontrolliert; steht kein Proxy davor, gilt
    ``Host``. Beides wird gleich streng behandelt: es entscheidet nur, welcher
    Registry-Eintrag gilt, und ein unbekannter Wert endet im 404.
    """
    forwarded = request.headers.get("x-forwarded-host")
    if forwarded:
        return forwarded
    return request.headers.get("host")


class ConcurrencyGate:
    """Decke für gleichzeitige Anfragen je Mandant (ADR-0021 D3).

    Ein Zähler je Mandant, je Prozess. Über der Decke gibt es **sofort** 503
    mit ``Retry-After`` und keine Warteschlange: die Decke liegt über Pool
    plus Overflow, wer sie reisst, hat also schon mehr in der Luft, als die
    Datenbank für ihn bedienen kann. Eine Warteschlange hielte an dieser
    Stelle nur Worker-Slots belegt — und zwar die, mit denen die **anderen**
    Kunden bedient werden.

    Ein eigener Zähler und keine ``asyncio.Semaphore``: eine Semaphore, die
    nicht warten darf, ist nur ein Zähler mit einem privaten Attribut, das man
    dann anfassen müsste. Ein Rennen gibt es nicht — zwischen Prüfung und
    Erhöhung liegt kein ``await``, in einer Event-Loop also kein
    Umschaltpunkt.

    Bewusst eine Nebenläufigkeits-Decke und keine Anfragen-pro-Minute-Grenze:
    was einen geteilten Prozess lähmt, ist Belegung und nicht Häufigkeit. Und
    bewusst je Prozess: prozessübergreifend bräuchte es gemeinsamen Zustand
    (Redis), und das wäre eine Abhängigkeit mehr im Anfragepfad. Bei mehreren
    Containern ist die wirksame Grenze ein Vielfaches davon — das gehört
    gesagt und steht in ADR-0021 unter „Preis".
    """

    def __init__(self, limit: int) -> None:
        self._limit = max(1, limit)
        self._in_flight: dict[str, int] = {}

    @property
    def limit(self) -> int:
        return self._limit

    def in_flight(self, slug: str) -> int:
        return self._in_flight.get(slug, 0)

    def try_enter(self, slug: str) -> bool:
        """Platz belegen. ``False``, wenn die Decke erreicht ist."""
        current = self._in_flight.get(slug, 0)
        if current >= self._limit:
            return False
        self._in_flight[slug] = current + 1
        return True

    def leave(self, slug: str) -> None:
        """Platz freigeben. Muss auch bei einer Ausnahme laufen."""
        current = self._in_flight.get(slug, 0) - 1
        if current > 0:
            self._in_flight[slug] = current
        else:
            # Auf 0 den Eintrag entfernen: bei vielen Kunden bleibt die
            # Zuordnung sonst als Sammlung von Nullen liegen.
            self._in_flight.pop(slug, None)


def _too_busy(tenant: Tenant, limit: int) -> JSONResponse:
    """503 für einen Kunden, der die Decke reisst — nur für ihn.

    ``warning`` und nicht ``error``: es ist ein Schutz, der greift, und keine
    Störung. Aber sichtbar, denn wenn es regelmässig passiert, ist entweder
    die Decke zu niedrig oder dieser Kunde braucht eine eigene Datenbank
    (ADR-0021 D5).
    """
    logger.warning(
        "Mandant %s über der Nebenläufigkeits-Decke (%d) — 503 für ihn, nicht für andere.",
        tenant.slug,
        limit,
    )
    return JSONResponse(
        status_code=503,
        content={"detail": "too_busy"},
        headers={"Retry-After": "2"},
    )


def _maintenance(tenant: Tenant, reason: str) -> JSONResponse:
    logger.warning(
        "Mandant %s wird mit 503 bedient: %s (Schema-Stand %r, Code-Kopf %r)",
        tenant.slug,
        reason,
        tenant.schema_version,
        HEAD_REVISION,
    )
    return JSONResponse(
        status_code=503,
        content={"detail": "maintenance"},
        headers={"Retry-After": "120"},
    )


def is_servable(tenant: Tenant) -> tuple[bool, str]:
    """Darf dieser Mandant jetzt bedient werden? Sonst mit Begründung nein."""
    if not tenant.status.serves_requests:
        return False, f"status={tenant.status.value}"
    # Ein leerer Stand heisst „noch nie über den Runner migriert" — der
    # Bestand vor dem Schema-Umzug. Der wird bedient, sonst stünde eine
    # bestehende Installation nach dem Update still.
    if tenant.schema_version and tenant.schema_version != HEAD_REVISION:
        return False, "schema_version != head"
    return True, ""


def has_tenant_key(
    tenant: Tenant, registry: TenantRegistry, settings: Settings
) -> tuple[bool, str]:
    """Liegt der Kundenschlüssel dieses Mandanten vor (ADR-0016 D8)?

    Der Fehlertext von ``resolve_tenant_keys`` erklärt den Grund; er geht ins
    Protokoll und nicht in die Antwort — die sagt nur „Wartung". Was der
    Betreiber falsch konfiguriert hat, ist keine Auskunft für einen Anwender.
    """
    try:
        resolve_tenant_keys(
            tenant.slug,
            fallback_audit_key=settings.audit_key.get_secret_value(),
            fallback_audit_key_id=settings.audit_key_id,
            fallback_secrets_key=settings.secrets_key.get_secret_value(),
            single_tenant=len(registry.tenants) == 1,
        )
    except TenantKeyError as exc:
        return False, f"kein Kundenschlüssel: {exc}"
    return True, ""


def make_tenant_middleware(
    read_registry: Callable[[], TenantRegistry] = get_registry,
    gate: ConcurrencyGate | None = None,
) -> Callable[[Request, Callable[[Request], Awaitable[Response]]], Awaitable[Response]]:
    """Middleware bauen. ``read_registry`` wird pro Anfrage aufgerufen, damit
    ein Test die Registry austauschen kann, ohne die Anwendung neu zu bauen.

    ``gate`` ist die Nebenläufigkeits-Decke je Mandant (ADR-0021 D3). ``None``
    heisst: aus den Einstellungen bauen, beim ersten Aufruf — die Decke lebt
    dann so lange wie die Anwendung. Ein Test kann eine eigene mit kleinem
    Wert übergeben, ohne die Einstellungen zu verbiegen.
    """
    holder: dict[str, ConcurrencyGate] = {} if gate is None else {"gate": gate}

    def _gate_for(settings: Settings) -> ConcurrencyGate:
        existing = holder.get("gate")
        if existing is None:
            existing = ConcurrencyGate(settings.tenant_concurrency_limit())
            holder["gate"] = existing
            logger.info(
                "Nebenläufigkeits-Decke je Mandant: %d gleichzeitige Anfragen "
                "in diesem Prozess (ADR-0021 D3).",
                existing.limit,
            )
        return existing

    async def resolve(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        if request.url.path in TENANT_FREE_PATHS:
            return await call_next(request)

        registry = read_registry()
        host = resolve_host(request)
        tenant = registry.resolve_host(host)
        if tenant is None:
            logger.warning("Unbekannter Hostname %r — 404", host)
            return JSONResponse(status_code=404, content={"detail": "unknown_tenant"})

        servable, reason = is_servable(tenant)
        if not servable:
            return _maintenance(tenant, reason)

        # Wie in auth/csrf.py: die Einstellungen aus app.state, wenn der
        # Lebenszyklus sie dort hinterlegt hat, sonst die aus der Umgebung.
        # Eine Middleware darf nicht daran scheitern, dass eine Anwendung
        # ohne Lifespan gebaut wurde — dann wäre jede Anfrage ein 500.
        settings: Settings = getattr(request.app.state, "settings", None) or get_settings()
        keyed, key_reason = has_tenant_key(tenant, registry, settings)
        if not keyed:
            return _maintenance(tenant, key_reason)

        # Die Decke zuletzt: erst wenn klar ist, dass dieser Kunde überhaupt
        # bedient wird, lohnt es sich, ihm einen Platz zu geben — und ein 404
        # oder eine Wartungsantwort soll keinen Platz belegen.
        limiter = _gate_for(settings)
        if not limiter.try_enter(tenant.slug):
            return _too_busy(tenant, limiter.limit)
        try:
            setattr(request.state, REQUEST_STATE_ATTR, tenant)
            return await call_next(request)
        finally:
            # `finally` und nicht nach dem `return`: eine Ausnahme aus einer
            # Route darf keinen Platz einbehalten, sonst schrumpft die Decke
            # mit jedem Fehler, bis der Kunde ausgesperrt ist.
            limiter.leave(tenant.slug)

    return resolve
