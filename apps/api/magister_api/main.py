"""FastAPI application factory."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from magister_api import __version__
from magister_api.audit.middleware import AuditContextMiddleware
from magister_api.auth.csrf import CsrfMiddleware
from magister_api.config import Settings, get_settings
from magister_api.db import dispose_engine, init_engine
from magister_api.logging_config import configure_logging
from magister_api.routers.auth import limiter as auth_limiter
from magister_api.routers.auth import router as auth_router
from magister_api.routers.classes import router as classes_router


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    settings: Settings = app.state.settings
    settings.require_runtime_secrets()
    init_engine(settings)
    yield
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

    app.include_router(auth_router)
    app.include_router(classes_router)

    @app.get("/healthz", tags=["meta"])
    async def healthz() -> dict[str, str]:
        return {"status": "ok", "version": __version__}

    return app


app = create_app()
