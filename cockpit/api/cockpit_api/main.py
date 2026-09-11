import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI
from starlette.requests import Request
from starlette.responses import Response

from cockpit_api.config import settings
from cockpit_api.management_guard import check_configuration, make_management_guard
from cockpit_api.routers import (
    backups,
    connector,
    console_auth,
    instances,
    offboarding,
    operator_access,
    service_tokens,
    templates,
    tenants,
    update_requests,
)
from cockpit_api.routers import settings as settings_router
from cockpit_api.services.health_poller import health_poller_loop
from cockpit_api.services.release_poller import release_poller_loop


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    # Refuse to start on a configuration that would expose the console
    # (ADR-0015 D1). Deliberately before the pollers: a console that must not
    # be reachable should not come up half-way.
    check_configuration(
        required=settings.require_management_listener,
        marker=settings.management_marker,
        published_address=settings.published_address,
        connector_marker=settings.connector_marker,
    )
    tasks = [
        asyncio.create_task(health_poller_loop()),
        asyncio.create_task(release_poller_loop()),
    ]
    try:
        yield
    finally:
        for t in tasks:
            t.cancel()


app = FastAPI(title="Vita Brevis Cockpit", version="0.2.0", lifespan=lifespan)

# Baseline security headers on every response. The Cockpit API only ever emits
# JSON, so the document context is locked down hard; ``frame-ancestors 'none'``
# is header-only (a meta CSP cannot set it) which is why it lives here rather
# than in the SPA's index.html (hardening-audit L-06). The SPA's own
# document-level CSP is delivered by the production reverse proxy, mirroring
# deploy/caddy/Caddyfile, once Cockpit is served in prod.
_SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'; base-uri 'none'",
    "Cross-Origin-Resource-Policy": "same-origin",
}


# Management-listener guard (ADR-0015 D1). Registered before the security
# headers so a refused request still carries them.
app.middleware("http")(
    make_management_guard(
        lambda: (settings.require_management_listener, settings.management_marker),
        lambda: settings.connector_marker,
    )
)


@app.middleware("http")
async def _security_headers(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    response = await call_next(request)
    for name, value in _SECURITY_HEADERS.items():
        response.headers.setdefault(name, value)
    return response


@app.get("/api/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


app.include_router(instances.router, prefix="/api")
app.include_router(service_tokens.router, prefix="/api")
app.include_router(update_requests.router, prefix="/api")
app.include_router(tenants.router, prefix="/api")
app.include_router(backups.router, prefix="/api")
app.include_router(offboarding.router, prefix="/api")
# Systemeinstellungen und Rechte-Matrix als Soll-Zustand (ADR-0017). Zwei
# Router, weil die Vorgaben plattformweit sind und die Abweichungen je Kunde.
app.include_router(settings_router.platform, prefix="/api")
app.include_router(templates.router, prefix="/api")
app.include_router(operator_access.router, prefix="/api")
app.include_router(console_auth.router, prefix="/api")
app.include_router(settings_router.tenant_scoped, prefix="/api")
app.include_router(connector.console, prefix="/api")
# Der Agentenpfad liegt NICHT unter /api: er kommt über den
# Connector-Listener (TCP 46200) und nicht über den Management-Listener.
app.include_router(connector.agent_api)
