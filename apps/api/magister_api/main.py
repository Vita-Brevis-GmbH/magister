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
from magister_api.db import dispose_engine, init_engine
from magister_api.logging_config import configure_logging
from magister_api.modules import catalog
from magister_api.modules.enforcement import make_module_guard
from magister_api.modules.platform import OPERATOR_ROUTERS
from magister_api.modules.registry import enabled_modules
from magister_api.modules.settings import PLATFORM_OWNED_ROUTERS
from magister_api.observability import runtime_snapshot
from magister_api.routers.auth import limiter as auth_limiter
from magister_api.services.ad_sync_scheduler import run_ad_sync_loop
from magister_api.services.app_settings import AppSettingsService
from magister_api.services.local_admin import LocalAdminService
from magister_api.services.rbac import RbacService
from magister_api.services.reconcile_loop import reconcile_loop
from magister_api.tenancy.context import (
    console_refresh_loop,
    dispose_tenancy,
    get_engines,
    get_registry,
    init_tenancy,
    refresh_from_console,
)
from magister_api.tenancy.keys import attach_keys, resolve_tenant_keys
from magister_api.tenancy.middleware import make_tenant_middleware
from magister_api.tenancy.registry import Tenant
from magister_api.tenancy.scope import apply_tenant_scope

logger = logging.getLogger(__name__)


async def _run_seeds(settings: Settings, tenant: Tenant) -> None:
    """Erst-Seeds für **einen** Mandanten, in dessen Schema.

    Wird nur bei genau einem Mandanten aufgerufen; die Begründung steht am
    Aufrufort im Lebenszyklus.
    """
    sm = get_engines().sessionmaker_for(tenant)
    async with sm() as seed_session:
        # Schlüssel und Scope wie im Anfragepfad: `app_settings` hat
        # verschlüsselte Spalten, und ohne `search_path` schreiben die Seeds
        # in das falsche Schema.
        attach_keys(
            seed_session,
            resolve_tenant_keys(
                tenant.slug,
                fallback_audit_key=settings.audit_key.get_secret_value(),
                fallback_audit_key_id=settings.audit_key_id,
                fallback_secrets_key=settings.app_secrets_key(),
                single_tenant=True,
            ),
        )
        await apply_tenant_scope(seed_session, tenant, extension_schema=settings.extension_schema)
        await LocalAdminService(seed_session).seed_from_env_if_empty(settings)
        # RBAC-Rollen und Standard-Rechte-Matrix (ADR-0010). Idempotent: füllt
        # nur eine leere Installation.
        await RbacService(seed_session).seed_defaults_if_empty()
        app_settings_svc = AppSettingsService(seed_session, settings)
        await app_settings_svc.seed_from_env_if_empty(settings)
        # Das Zertifikat des Webservers materialisieren (eigenes oder
        # selbstsigniert), damit der Reverse Proxy sein Snippet hat, bevor er
        # (neu) startet. Ohne MAGISTER_WEB_CERT_DIR ein No-op (Entwicklung,
        # Tests). Nicht fatal, aber LAUT: scheitert es still (etwa ein
        # root-eigenes /certs, in das die API nicht schreiben darf), bekommt
        # Caddy nie sein `import /certs/tls.caddy` und startet nicht.
        try:
            await app_settings_svc.materialize_web_tls()
        except Exception:
            logger.exception(
                "Snippet für das Webserver-Zertifikat konnte nicht in %s "
                "geschrieben werden; der Reverse Proxy startet unter Umständen "
                "nicht, bis das behoben ist (ist das Verzeichnis für den "
                "API-Benutzer beschreibbar?).",
                settings.web_cert_dir,
            )


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    settings: Settings = app.state.settings
    settings.require_runtime_secrets()
    settings.reject_removed_env()
    init_engine(settings)
    # Mandanten-Registry und Engines (ADR-0013 D1). Bewusst vor den Seeds: eine
    # unbrauchbare Registry soll den Start abbrechen, nicht erst die erste
    # Anfrage — ein Prozess, der niemanden bedienen kann, soll auch nicht
    # gesund melden.
    registry, _ = init_tenancy(settings)
    # Ein erster Abruf beim Start, damit ein gerade in der Konsole angelegter
    # Kunde nicht bis zum nächsten Intervall wartet. Scheitert er, bleibt der
    # Stand aus der Umgebung — der Prozess startet trotzdem (ADR-0013 D4).
    if settings.console_registry_url:
        await refresh_from_console(settings)
        registry = get_registry()
    logger.info(
        "Mandantenfähigkeit aktiv: %d Mandant(en), Erweiterungsschema %r, Registry aus %s",
        len(registry.tenants),
        settings.extension_schema,
        "Konsole" if settings.console_registry_url else "Umgebung",
    )

    # First-run seeds. Idempotent: sie füllen nur eine leere Installation.
    #
    # **Im Schema des Mandanten und nicht im `public` des Prozesses**
    # (ADR-0021 D4, dieselbe Ursache wie beim AD-Abgleich). `get_sessionmaker()`
    # hängt an `MAGISTER_DATABASE_URL`, und dort liegen bei einer gehosteten
    # Installation gar keine Magister-Tabellen mehr — nur die Erweiterungen.
    # Die Seeds hätten in eine leere `public` geschrieben und den Start
    # abgebrochen: eine frische gehostete Installation wäre nicht hochgekommen.
    #
    # Ab zwei Mandanten werden sie **übersprungen**. Was sie setzen, kommt dort
    # aus der Konsole (Einstellungen und Rechte-Matrix, ADR-0017) oder aus der
    # Bereitstellung — und ein Notkonto aus einer prozessweiten
    # Umgebungsvariable wäre bei zwanzig Kunden zwanzigmal dasselbe Passwort.
    if len(registry.tenants) == 1:
        await _run_seeds(settings, registry.tenants[0])
    else:
        logger.info(
            "Erst-Seeds übersprungen: %d Mandanten. Einstellungen und Rechte "
            "kommen aus der Konsole, das Schema aus der Bereitstellung.",
            len(registry.tenants),
        )

    # Periodic AD sync (interval from app_settings, GUI-editable at runtime).
    # The recurring AD *read* must run in exactly ONE container: the single
    # AD-owning process keeps MAGISTER_RUN_SCHEDULER on (default); every other
    # container in a split deployment sets it to 0 so it never opens a second
    # sync loop against AD + DB.
    stop_event = asyncio.Event()
    sync_task: asyncio.Task[None] | None = None
    # Registry-Abruf läuft in JEDEM Container: jeder hat seinen eigenen
    # Zwischenspeicher, weil jeder selbst auflöst. Anders als der AD-Sync ist
    # das kein exklusiver Vorgang — es ist ein Lesevorgang ohne Nebenwirkung.
    registry_task: asyncio.Task[None] | None = None
    # Der Abgleich des Soll-Zustands (ADR-0017) hängt an derselben Bedingung
    # und läuft ebenfalls in jedem Container: er schreibt nur Differenzen, und
    # zwei Container finden dieselbe Differenz nur einmal.
    reconcile_task: asyncio.Task[None] | None = None
    if settings.console_registry_url:
        registry_task = asyncio.create_task(
            console_refresh_loop(settings, stop=stop_event), name="console-registry-refresh"
        )
        reconcile_task = asyncio.create_task(
            reconcile_loop(settings, stop=stop_event), name="platform-settings-reconcile"
        )
    if settings.run_scheduler:
        sync_task = asyncio.create_task(
            run_ad_sync_loop(settings, stop_event=stop_event),
            name="ad-sync-scheduler",
        )
        logger.info("AD-sync scheduler started (this container owns the AD read loop)")
    else:
        logger.info(
            "AD-sync scheduler disabled (MAGISTER_RUN_SCHEDULER=0); "
            "the AD read loop runs in another container"
        )

    try:
        yield
    finally:
        stop_event.set()
        if registry_task is not None:
            registry_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await registry_task
        if reconcile_task is not None:
            reconcile_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await reconcile_task
        if sync_task is not None:
            sync_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await sync_task
        await dispose_tenancy()
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
    # The tenant resolution has to run BEFORE all of them — added last of all, so
    # it executes first: an unknown host must be a 404 before anything opens a
    # session, and everything downstream may rely on request.state.tenant.
    app.add_middleware(SlowAPIMiddleware)
    app.add_middleware(CsrfMiddleware)
    app.add_middleware(AuditContextMiddleware)
    app.middleware("http")(make_tenant_middleware())

    # Feature modules own their routers (M6 — magister_api/modules). Toggleable
    # modules get a mount-time guard dependency so a disabled module's routes
    # 404 at request time (Phase 3), not just disappear from the nav; the
    # non-toggleable platform base is always reachable.
    #
    # Von der Plattform verwaltet (ADR-0017 D1): steht eine Konsolen-URL, holt
    # diese Installation ihre Mandanten von dort — dann gehören
    # Systemeinstellungen und Rechte-Matrix dem Betreiber, und die zwei Router
    # werden GAR NICHT gemountet. Nicht mit einer Prüfung davor: ein Endpunkt,
    # der antwortet „das darfst du nicht", ist noch da und kann eine Lücke
    # haben. Ohne Konsole (Einzelinstallation) bleibt alles wie bisher — dort
    # ist der Kunde der Betreiber.
    platform_managed = bool(s.console_registry_url)
    # Über `id()` und nicht über ein Set: `APIRouter` ist nicht hashbar. Ein
    # `set(...)` davon wirft `TypeError: unhashable type` — beim Start, also
    # sofort, aber es kostet zehn Minuten, wenn man es nicht erwartet.
    skip = {id(r) for r in PLATFORM_OWNED_ROUTERS} if platform_managed else set()
    if not s.operator_public_key.strip():
        # Kein hinterlegter Schlüssel heisst: kein Operator-Zugriff, und die
        # Fläche existiert nicht (ADR-0019 D3).
        skip |= {id(r) for r in OPERATOR_ROUTERS}
    for module in enabled_modules(s.container_modules):
        meta = catalog.get_meta(module.id)
        guard = (
            [Depends(make_module_guard(module.id))] if meta is not None and meta.toggleable else []
        )
        for router in module.routers:
            if id(router) in skip:
                continue
            app.include_router(router, dependencies=guard)
    if platform_managed:
        logger.info(
            "Von der Plattform verwaltet: %d Router der Kunden-API nicht gemountet "
            "(Systemeinstellungen, Rechte-Matrix). Sie kommen aus der Konsole.",
            len(PLATFORM_OWNED_ROUTERS),
        )

    # Internal AD-RPC server (ADR-0011). Mounted only in an AD-capable process
    # (no RPC URL configured — None or empty) — the monolith or the dedicated
    # ``ad`` container; a client container reaches AD through THIS surface,
    # never re-exposes it. It sits off the Caddy ``/api/*`` route and is
    # secret-guarded. Truthiness (not ``is None``) so a compose override that
    # blanks the URL on the AD owner still counts as AD-capable.
    if not s.ad_rpc_url:
        from magister_api.routers.ad_rpc import router as ad_rpc_router

        app.include_router(ad_rpc_router)

    @app.get("/healthz", tags=["meta"])
    async def healthz() -> dict[str, str]:
        return {"status": "ok", "version": __version__}

    @app.get("/runtime", tags=["meta"])
    async def runtime() -> dict[str, object]:
        # Per-container facts (mounted modules, scheduler ownership, DB-pool,
        # RSS). Internal only — reachable like /healthz, not routed publicly.
        return {"version": __version__, **runtime_snapshot(s)}

    return app


app = create_app()
