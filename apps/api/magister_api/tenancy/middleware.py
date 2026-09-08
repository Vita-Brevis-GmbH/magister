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
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable

from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from magister_api.tenancy.context import REQUEST_STATE_ATTR, get_registry
from magister_api.tenancy.registry import Tenant, TenantRegistry
from magister_api.tenancy.version import HEAD_REVISION

logger = logging.getLogger(__name__)

#: Pfade, die ohne Mandanten beantwortet werden. Bewusst kurz: das sind die
#: beiden internen Sonden, die auch bei einem kaputten Registry-Eintrag noch
#: antworten müssen, damit ein Orchestrierer den Container nicht endlos neu
#: startet, während er nur eine Zeile Konfiguration braucht.
TENANT_FREE_PATHS: frozenset[str] = frozenset({"/healthz", "/runtime"})


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


def make_tenant_middleware(
    read_registry: Callable[[], TenantRegistry] = get_registry,
) -> Callable[[Request, Callable[[Request], Awaitable[Response]]], Awaitable[Response]]:
    """Middleware bauen. ``read_registry`` wird pro Anfrage aufgerufen, damit
    ein Test die Registry austauschen kann, ohne die Anwendung neu zu bauen."""

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

        setattr(request.state, REQUEST_STATE_ATTR, tenant)
        return await call_next(request)

    return resolve
