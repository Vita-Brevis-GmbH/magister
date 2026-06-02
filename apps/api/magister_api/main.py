"""FastAPI application factory."""

from __future__ import annotations

import asyncio
import contextlib
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
from magister_api.db import dispose_engine, get_sessionmaker, init_engine
from magister_api.logging_config import configure_logging
from magister_api.routers.admin_local_admin import router as admin_local_admin_router
from magister_api.routers.admin_settings import router as admin_settings_router
from magister_api.routers.admin_sync import router as admin_sync_router
from magister_api.routers.auth import limiter as auth_limiter
from magister_api.routers.auth import router as auth_router
from magister_api.routers.class_memberships import router as class_memberships_router
from magister_api.routers.class_teachers import router as class_teachers_router
from magister_api.routers.classes import router as classes_router
from magister_api.routers.imports import router as imports_router
from magister_api.routers.letters import router as letters_router
from magister_api.routers.privacy import router as privacy_router
from magister_api.routers.reports import router as reports_router
from magister_api.routers.student_password_reset import router as student_pw_reset_router
from magister_api.routers.substitutions import router as substitutions_router
from magister_api.routers.teacher_password_reset import router as teacher_pw_reset_router
from magister_api.routers.users import router as users_router
from magister_api.services.ad_sync_scheduler import run_ad_sync_loop
from magister_api.services.app_settings import AppSettingsService
from magister_api.services.local_admin import LocalAdminService


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
        await AppSettingsService(seed_session, settings).seed_from_env_if_empty(settings)

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

    app.include_router(auth_router)
    app.include_router(classes_router)
    app.include_router(class_teachers_router)
    app.include_router(class_memberships_router)
    app.include_router(users_router)
    app.include_router(admin_sync_router)
    app.include_router(admin_local_admin_router)
    app.include_router(admin_settings_router)
    app.include_router(imports_router)
    app.include_router(letters_router)
    app.include_router(privacy_router)
    app.include_router(reports_router)
    app.include_router(student_pw_reset_router)
    app.include_router(substitutions_router)
    app.include_router(teacher_pw_reset_router)

    @app.get("/healthz", tags=["meta"])
    async def healthz() -> dict[str, str]:
        return {"status": "ok", "version": __version__}

    return app


app = create_app()
