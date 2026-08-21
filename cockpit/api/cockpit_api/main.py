import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI
from starlette.requests import Request
from starlette.responses import Response

from cockpit_api.routers import instances, service_tokens, update_requests
from cockpit_api.services.health_poller import health_poller_loop
from cockpit_api.services.release_poller import release_poller_loop


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
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
