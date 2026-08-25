"""FastAPI application factory."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from magister_api import __version__
from magister_api.audit.middleware import AuditContextMiddleware
from magister_api.auth.csrf import CsrfMiddleware
from magister_api.config import Settings, get_settings
from magister_api.db import dispose_engine, get_sessionmaker, init_engine
from magister_api.logging_config import configure_logging
from magister_api.modules import catalog
from magister_api.modules.enforcement import make_module_guard
from magister_api.modules.registry import enabled_modules
from magister_api.routers.auth import limiter as auth_limiter
from magister_api.services.ad_sync_scheduler import run_ad_sync_loop
from magister_api.services.app_settings import AppSettingsService
from magister_api.services.local_admin import LocalAdminService
from magister_api.services.rbac import RbacService

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    settings: Settings = app.state.settings
    settings.require_runtime_secrets()
    init_engine(settings)

    # First-run seeds. Both are idempotent and short-circuit when the
    # respective rows are already populated.
    sm = get_sessionmaker()
    async with sm() as seed_session:
        await LocalAdminService(seed_session).seed_from_env_if_empty(settings)
        # RBAC roles + default capability matrix (ADR-0010). Idempotent: only
        # populates an empty install, so behaviour matches the former static map.
        await RbacService(seed_session).seed_defaults_if_empty()
        app_settings_svc = AppSettingsService(seed_session, settings)
        await app_settings_svc.seed_from_env_if_empty(settings)
        # Materialize the webserver cert (custom or self-signed fallback) so the
        # reverse proxy has a snippet to import before it (re)starts. No-op when
        # MAGISTER_WEB_CERT_DIR is unset (dev/tests). Non-fatal, but LOUD: if this
        # silently fails (e.g. a root-owned /certs volume the non-root API can't
        # write), Caddy never gets its `import /certs/tls.caddy` snippet and won't
        # start — so the failure must be visible in the API logs, not swallowed.
        try:
            await app_settings_svc.materialize_web_tls()
        except Exception:
            logger.exception(
                "Failed to materialize webserver TLS snippet into %s; "
                "the reverse proxy may not start until this is resolved "
                "(check that the cert dir is writable by the API user).",
                settings.web_cert_dir,
            )

    # Periodic AD sync (interval from app_settings, GUI-editable at runtime).
    stop_event = asyncio.Event()
    sync_task = asyncio.create_task(
        run_ad_sync_loop(settings, sm, stop_event=stop_event),
        name="ad-sync-scheduler",
    )

    try:
        yield
    finally:
        stop_event.set()
        sync_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await sync_task
        await dispose_engine()


def create_app(settings: Settings | None = None) -> FastAPI:
    s = settings or get_settings()
    configure_logging(s.log_level)
    app = FastAPI(
        title="Magister API",
        version=__version__,
        lifespan=lifespan,
    )
    app.state.settings = s
    app.state.limiter = auth_limiter

    @app.exception_handler(RateLimitExceeded)
    async def _rate_limit_handler(_: Request, exc: RateLimitExceeded) -> JSONResponse:
        return JSONResponse(
            status_code=429, content={"detail": "rate_limited", "retry_after": str(exc.detail)}
        )

    # Order matters: CSRF needs to see request.state.* set by AuditContextMiddleware,
    # so AuditContext is added LAST (Starlette executes middleware in reverse order).
    app.add_middleware(SlowAPIMiddleware)
    app.add_middleware(CsrfMiddleware)
    app.add_middleware(AuditContextMiddleware)

    # Feature modules own their routers (M6 — magister_api/modules). Toggleable
    # modules get a mount-time guard dependency so a disabled module's routes
    # 404 at request time (Phase 3), not just disappear from the nav; the
    # non-toggleable platform base is always reachable.
    for module in enabled_modules():
        meta = catalog.get_meta(module.id)
        guard = (
            [Depends(make_module_guard(module.id))] if meta is not None and meta.toggleable else []
        )
        for router in module.routers:
            app.include_router(router, dependencies=guard)

    @app.get("/healthz", tags=["meta"])
    async def healthz() -> dict[str, str]:
        return {"status": "ok", "version": __version__}

    return app


app = create_app()
